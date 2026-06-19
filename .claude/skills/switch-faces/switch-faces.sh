#!/usr/bin/env bash
# switch-faces: at speech pauses, hard-cut to a non-speaking LISTENER's face
# cropped from the 16:9 source — the reaction shot a real editor cuts to while
# the speaker breathes. Deterministic — no Claude. Timeline-preserving (audio
# copied untouched, total duration identical) so every downstream timestamp
# stays valid. Runs on the clean 1080x1920 vertical AFTER zoom-punch and BEFORE
# broll/captions, so cutaways can still override and captions burn on top. Needs
# a real second face — solo talking-heads pass through. SWITCH_FACES=0 disables.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"

input="${1:-}"       # base 1080x1920 vertical to composite onto
src16="${2:-}"       # the pre-vertical 16:9 source (holds the listener's face)
transcript="${3:-}"  # clip-local word-timed transcript (same timeline as input)
out="${4:-}"
chunks="${5:-}"      # optional chunk-captions json — phrase boundaries to switch on

if [[ -z "$input" || -z "$src16" || -z "$transcript" || -z "$out" ]]; then
  echo "usage: switch-faces.sh <base_vert.mp4> <source16x9.mp4> <transcript.json> <out.mp4> [chunks.json]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "switch-faces: input not found: $input" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
sig="$(mtime "$input")|$([[ -f "$src16" ]] && mtime "$src16" || echo 0)|$([[ -f "$transcript" ]] && mtime "$transcript" || echo 0)|$([[ -n "$chunks" && -f "$chunks" ]] && mtime "$chunks" || echo 0)|${SWITCH_FACES:-1}|v2"
meta="$out.sfmeta"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "switch-faces: cache hit at $out" >&2
  echo "$out"; exit 0
fi
mkdir -p "$(dirname "$out")"

passthrough() {
  ffmpeg -y -hide_banner -loglevel error -i "$input" -c copy "$out" 2>/dev/null || cp "$input" "$out"
  printf '%s' "$sig" > "$meta"
  echo "$out"
}

if [[ "${SWITCH_FACES:-1}" == "0" ]]; then
  echo "switch-faces: disabled (SWITCH_FACES=0) — passthrough" >&2
  passthrough; exit 0
fi
if [[ ! -f "$src16" || ! -f "$transcript" ]]; then
  echo "switch-faces: missing 16:9 source or transcript — passthrough" >&2
  passthrough; exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

cargs=()
[[ -n "$chunks" && -f "$chunks" ]] && cargs+=("$chunks")
if ! python3 "$here/plan.py" "$src16" "$transcript" "${cargs[@]+"${cargs[@]}"}" > "$tmp/plan.json" 2>"$tmp/plan.err"; then
  echo "switch-faces: plan failed — passthrough" >&2
  cat "$tmp/plan.err" >&2
  passthrough; exit 0
fi

flt="$(python3 - "$tmp/plan.json" <<'PY'
import json, sys
wins = json.load(open(sys.argv[1])).get("windows", [])
if not wins:
    print(""); sys.exit(0)
W, H = 1080, 1920
n = len(wins)
g = f"[1:v]split={n}" + "".join(f"[w{i}]" for i in range(n)) + ";"
for i, w in enumerate(wins):
    cw, ch, cx, cy = w["crop"]
    g += (f"[w{i}]trim={w['t0']:.3f}:{w['t1']:.3f},setpts=PTS-STARTPTS+{w['t0']:.3f}/TB,"
          f"crop={cw}:{ch}:{cx}:{cy},scale={W}:{H},setsar=1[c{i}];")
last = "0:v"
for i, w in enumerate(wins):
    o = "vout" if i == n - 1 else f"o{i}"
    g += f"[{last}][c{i}]overlay=enable='between(t,{w['t0']:.3f},{w['t1']:.3f})'[{o}];"
    last = o
print(g.rstrip(";"))
PY
)"

if [[ -z "$flt" ]]; then
  echo "switch-faces: no listener / no pause windows — passthrough" >&2
  passthrough; exit 0
fi

nwin="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["windows"]))' "$tmp/plan.json")"
has_audio="$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$input" 2>/dev/null | head -1)"

declare -a venc dec thr amap
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do dec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do thr+=("$a"); done < <(vt_threads)
amap=(-map 0:a -c:a copy)
[[ -z "$has_audio" ]] && amap=()

if ! ffmpeg -y -hide_banner -loglevel error \
  "${dec[@]+"${dec[@]}"}" -i "$input" -i "$src16" \
  -filter_complex "$flt" -map "[vout]" "${amap[@]}" \
  "${venc[@]}" "${thr[@]}" -movflags +faststart \
  "$out" 2>"$tmp/err.log"; then
  echo "switch-faces: ffmpeg failed — passthrough" >&2
  cat "$tmp/err.log" >&2
  passthrough; exit 0
fi

printf '%s' "$sig" > "$meta"
echo "switch-faces: wrote $out ($nwin reaction cut(s))" >&2
echo "$out"
