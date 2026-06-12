#!/usr/bin/env bash
# broll-composite: hard-cut full-frame b-roll cutaways onto a 1080x1920 clip per
# broll_plan.json. Video re-encoded; podcast audio stream-copied. Zero valid
# picks -> passthrough copy. Pure ffmpeg.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"

in_clip="${1:-}"
plan="${2:-}"
out="${3:-}"

if [[ -z "$in_clip" || -z "$plan" || -z "$out" ]]; then
  echo "usage: broll-composite.sh <in_clip.mp4> <broll_plan.json> <out.mp4>" >&2
  exit 2
fi
[[ -f "$in_clip" ]] || { echo "broll-composite: clip not found: $in_clip" >&2; exit 2; }
[[ -f "$plan"    ]] || { echo "broll-composite: plan not found: $plan" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
sfx="${BROLL_SFX:-1}"
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
sig="$(mtime "$in_clip")|$(mtime "$plan")|v2|sfx=$sfx"
meta="$out.compmeta"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "broll-composite: cache hit at $out" >&2
  echo "$out"; exit 0
fi
mkdir -p "$(dirname "$out")"

passthrough() {
  ffmpeg -y -hide_banner -loglevel error -i "$in_clip" -c copy "$out" 2>/dev/null \
    || cp "$in_clip" "$out"
  printf '%s' "$sig" > "$meta"
  echo "broll-composite: passthrough (no valid picks)" >&2
  echo "$out"
}

fb="$(python3 "$here/build_filter.py" "$plan")"
flt="${fb%|*}"; n="${fb##*|}"
if [[ "$n" -eq 0 || -z "$flt" ]]; then passthrough; exit 0; fi

# collect b-roll inputs in t0 order (match build_filter.py ordering)
declare -a inputs=(-i "$in_clip")
while IFS= read -r c; do
  [[ -z "$c" ]] && continue
  inputs+=(-i "$c")
done < <(python3 -c '
import json,sys,os
ps=[p for p in json.load(open(sys.argv[1])).get("picks",[]) if p.get("clip_path") and os.path.exists(p["clip_path"])]
ps.sort(key=lambda p:p["t0"])
[print(p["clip_path"]) for p in ps]
' "$plan")

declare -a venc dec thr
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do dec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do thr+=("$a"); done < <(vt_threads)

# whoosh SFX on each cutaway in/out (BROLL_SFX=0 disables). The podcast audio
# stays continuous — it is amix'd with the whoosh bed, never replaced.
declare -a amap=(-map 0:a? -c:a copy)
has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$in_clip" 2>/dev/null || true)"
if [[ "$sfx" != "0" && "$has_audio" == "audio" ]]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  dur="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$in_clip")"
  python3 -c '
import json,sys,os
ps=[p for p in json.load(open(sys.argv[1])).get("picks",[]) if p.get("clip_path") and os.path.exists(p["clip_path"])]
ev=[]
for p in ps:
    ev.append({"t":float(p["t0"]),"dir":"in"})
    ev.append({"t":float(p["t1"]),"dir":"out"})
json.dump(ev,open(sys.argv[2],"w"))' "$plan" "$tmp/events.json"
  if python3 "$here/make_whoosh.py" "$tmp/whoosh.wav" "$dur" 44100 "$tmp/events.json" 2>/dev/null; then
    inputs+=(-i "$tmp/whoosh.wav")
    widx=$((n + 1))
    flt="$flt;[0:a][$widx:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.97[aout]"
    amap=(-map "[aout]" -c:a aac -b:a 192k)
  fi
fi

if ffmpeg -y -hide_banner -loglevel error \
    "${dec[@]+"${dec[@]}"}" "${inputs[@]}" \
    -filter_complex "$flt" \
    -map "[vout]" "${amap[@]}" \
    "${venc[@]}" "${thr[@]}" -movflags +faststart \
    "$out" 2>"$out.fferr"; then
  rm -f "$out.fferr"
  printf '%s' "$sig" > "$meta"
  echo "broll-composite: wrote $out ($n cutaways)" >&2
  echo "$out"
else
  echo "broll-composite: ffmpeg failed, passing through" >&2
  cat "$out.fferr" >&2; rm -f "$out.fferr"
  passthrough
fi
