#!/usr/bin/env bash
# burn-subtitles: burn word-timed subtitles from a transcript.json into a video.
# This ffmpeg build has no libass/drawtext, so subtitles are rendered as a PNG
# overlay sequence (PIL) and composited with ffmpeg's overlay filter.
set -euo pipefail

input="${1:-}"
transcript="${2:-}"
out="${3:-}"
style="${4:-chunks}"
font_size="${5:-72}"

if [[ -z "$input" || -z "$transcript" || -z "$out" ]]; then
  echo "usage: burn-subtitles.sh <input> <transcript_or_chunks.json> <out> [style:chunks|line|word-karaoke|selective] [font_size]" >&2
  echo "  style=chunks (default): second arg is chunks.json from chunk-captions" >&2
  echo "  other styles: second arg is transcript.json" >&2
  exit 2
fi
for f in "$input" "$transcript"; do
  [[ -f "$f" ]] || { echo "burn-subtitles: not found: $f" >&2; exit 2; }
done
case "$style" in
  chunks|line|word-karaoke|selective) ;;
  *) echo "burn-subtitles: unknown style: $style" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "$0")" && pwd)"

if [[ -f "$out" ]]; then
  o="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  i="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  t="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
  if [[ "$o" -ge "$i" && "$o" -ge "$t" ]]; then
    echo "burn-subtitles: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

read -r w h rate dur < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate \
  -show_entries format=duration -of default=nw=1:nk=1 "$input" | paste -sd' ' -)
[[ "$w" =~ ^[0-9]+$ && "$h" =~ ^[0-9]+$ ]] || {
  echo "burn-subtitles: could not read video dimensions" >&2; exit 1; }

fps="$(python3 -c "n,d='$rate'.split('/'); print(float(n)/float(d))")"
nframes="$(python3 -c "import math; print(int(round($dur*$fps)))")"

# OVERLAY_PLAN_ONLY: render the PNG sequence to a STABLE sidecar dir and emit a
# base-relative *.overlay.json instead of encoding. The fused compositor applies
# it with the title + brand specs in one captions-cluster pass.
if [[ "${OVERLAY_PLAN_ONLY:-0}" != "0" ]]; then
  seq="${out}.assets"
  rm -rf "$seq"; mkdir -p "$seq"
  python3 "$here/burn_subtitles.py" "$transcript" "$seq" "$w" "$h" \
    "$fps" "$nframes" "$style" "$font_size" "$input"
  python3 - "$out" "$seq/%06d.png" "$fps" <<'PY'
import json, sys
out, seqpat, fps = sys.argv[1:4]
spec = {
  "inputs": [{"path": seqpat, "framerate": float(fps)}],
  "filter": "[{IN}][{L0}]overlay=format=auto[{OUT}]",
  "audio": None,
  "quality": "mid",
}
json.dump(spec, open(out, "w"), indent=2)
PY
  echo "burn-subtitles: plan-only spec -> $out  ${w}x${h}  style=$style" >&2
  echo "$out"; exit 0
fi

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
seq="$tmp/seq"
mkdir -p "$seq"

python3 "$here/burn_subtitles.py" "$transcript" "$seq" "$w" "$h" \
  "$fps" "$nframes" "$style" "$font_size" "$input"

staging="$tmp/$(basename "$out")"

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

ffmpeg -y -hide_banner -loglevel error \
  ${vdec[@]+"${vdec[@]}"} -i "$input" \
  -framerate "$fps" -i "$seq/%06d.png" \
  -filter_complex "[0:v][1:v]overlay=format=auto:shortest=1[v]" \
  -map "[v]" -map 0:a? \
  "${venc[@]}" -c:a copy \
  "${vthr[@]}" -movflags +faststart "$staging"

mv "$staging" "$out"
echo "burn-subtitles: wrote $out  ${w}x${h}  style=$style" >&2
echo "$out"
