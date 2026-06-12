#!/usr/bin/env bash
# zoom-punch: quick punch-in zooms at the clip's loudest words. Deterministic
# (RMS peaks snapped to word starts) — no Claude. Crop biases to the upper
# third so the speaker's eyeline holds steady through the punch.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"

input="${1:-}"
transcript="${2:-}"
out="${3:-}"
strength="${4:-0.10}"

if [[ -z "$input" || -z "$transcript" || -z "$out" ]]; then
  echo "usage: zoom-punch.sh <in.mp4> <transcript.json> <out.mp4> [strength=0.10]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "zoom-punch: input not found: $input" >&2; exit 2; }
[[ -f "$transcript" ]] || { echo "zoom-punch: transcript not found: $transcript" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
sig="$(mtime "$input")|$(mtime "$transcript")|$strength|v1"
meta="$out.zpmeta"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "zoom-punch: cache hit at $out" >&2
  echo "$out"; exit 0
fi
mkdir -p "$(dirname "$out")"

dur="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$input")"
[[ -n "$dur" ]] || { echo "zoom-punch: could not read duration" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/../pick-segments/rms.py" "$input" > "$tmp/rms.json" 2>/dev/null \
  || echo '{"rms":[]}' > "$tmp/rms.json"
python3 "$here/plan.py" "$transcript" "$tmp/rms.json" "$dur" > "$tmp/times.json"

flt="$(python3 - "$tmp/times.json" "$strength" <<'PY'
import json, sys
times = json.load(open(sys.argv[1]))
s = float(sys.argv[2])
if not times:
    print("")
    sys.exit(0)
# pulse: 0.1s attack, ~0.35s hold, 0.18s release
pulses = "+".join(
    f"min(max((t-{t})/0.1,0),1)*min(max(1-(t-{t}-0.45)/0.18,0),1)" for t in times)
z = f"(1+{s}*({pulses}))"
# crop w/h are init-only (t=NaN there) — animate by scaling UP per-frame
# (scale eval=frame DOES re-evaluate t) then cropping back to a static
# 1080x1920 window; crop x/y are per-frame so the window tracks the zoom.
print(
    f"scale=w='trunc(iw*{z}/2)*2':h='trunc(ih*{z}/2)*2':eval=frame,"
    f"crop=1080:1920:x='(iw-1080)/2':y='(ih-1920)/3'"
)
PY
)"

if [[ -z "$flt" ]]; then
  ffmpeg -y -hide_banner -loglevel error -i "$input" -c copy "$out" 2>/dev/null \
    || cp "$input" "$out"
  printf '%s' "$sig" > "$meta"
  echo "zoom-punch: no punch moments — passthrough" >&2
  echo "$out"; exit 0
fi

n_punch="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$tmp/times.json")"

declare -a venc dec thr
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do dec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do thr+=("$a"); done < <(vt_threads)

ffmpeg -y -hide_banner -loglevel error \
  "${dec[@]+"${dec[@]}"}" -i "$input" \
  -vf "$flt" \
  "${venc[@]}" "${thr[@]}" -c:a copy -movflags +faststart \
  "$out" || { echo "zoom-punch: ffmpeg failed" >&2; exit 1; }

printf '%s' "$sig" > "$meta"
echo "zoom-punch: wrote $out ($n_punch punch-in(s))" >&2
echo "$out"
