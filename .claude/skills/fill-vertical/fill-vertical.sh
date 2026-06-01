#!/usr/bin/env bash
# fill-vertical: punch-in 9:16 reframe — fill the frame, never letterbox.
set -euo pipefail

input="${1:-}"
out="${2:-}"
target="${3:-1080x1920}"
face_frac="${4:-0.45}"
max_zoom="${5:-2.0}"
scene_thresh="${6:-0.4}"
samples="${7:-5}"

if [[ -z "$input" || -z "$out" ]]; then
  echo "usage: fill-vertical.sh <input> <out> [target=1080x1920] [face_frac=0.45] [max_zoom=2.0] [scene_thresh=0.4] [samples=5]" >&2
  exit 2
fi
if [[ ! -f "$input" ]]; then
  echo "fill-vertical: input not found: $input" >&2
  exit 2
fi

w="${target%x*}"
h="${target#*x}"
if [[ -z "$w" || -z "$h" || "$w" == "$target" ]]; then
  echo "fill-vertical: bad target '$target' (expected WxH)" >&2
  exit 2
fi

if [[ -f "$out" ]]; then
  in_mtime="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  out_mtime="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$out_mtime" -ge "$in_mtime" ]]; then
    echo "fill-vertical: cache hit at $out" >&2
    exit 0
  fi
fi

here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# 1) plan: scene-detect + per-shot crop boxes
plan="$(python3 "$here/fill_vertical.py" "$input" "$out" \
  --target "$target" --face_frac "$face_frac" --max_zoom "$max_zoom" \
  --scene_thresh "$scene_thresh" --samples "$samples")"

# shellcheck disable=SC1091
source "$(cd "$here/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' x; do venc+=("$x"); done < <(vt_args low)
while IFS= read -r -d '' x; do vdec+=("$x"); done < <(vt_decode_args)
while IFS= read -r -d '' x; do vthr+=("$x"); done < <(vt_threads)

# 2) render each shot: cut -> crop -> scale, video only (audio added at join)
nshots="$(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["shots"]))' "$plan")"
concat="$tmp/concat.txt"
: > "$concat"
for ((i=0; i<nshots; i++)); do
  read -r t0 t1 cw ch cx cy < <(python3 -c '
import json,sys
s=json.load(open(sys.argv[1]))["shots"][int(sys.argv[2])]
c=s["crop"]
print(s["t0"],s["t1"],c[0],c[1],c[2],c[3])' "$plan" "$i")
  seg="$tmp/seg_$i.mp4"
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -ss "$t0" -to "$t1" -i "$input" \
    -an -vf "crop=${cw}:${ch}:${cx}:${cy},scale=${w}:${h},setsar=1" \
    "${venc[@]}" "${vthr[@]}" "$seg"
  echo "file '$seg'" >> "$concat"
done

staging="$tmp/$(basename "$out")"
if [[ "$nshots" -eq 1 ]]; then
  # single shot: re-mux original audio straight onto the rendered video
  ffmpeg -y -hide_banner -loglevel error \
    -i "$tmp/seg_0.mp4" -i "$input" \
    -map 0:v:0 -map 1:a:0? -c:v copy -c:a copy \
    "${vthr[@]}" -movflags +faststart "$staging"
else
  # 3) concat video segments, stream-copy original audio over the whole clip
  ffmpeg -y -hide_banner -loglevel error \
    -f concat -safe 0 -i "$concat" -i "$input" \
    -map 0:v:0 -map 1:a:0? -c:v copy -c:a copy \
    "${vthr[@]}" -movflags +faststart "$staging"
fi

mv "$staging" "$out"
echo "fill-vertical: wrote $out (${w}x${h}, ${nshots} shot(s))" >&2
