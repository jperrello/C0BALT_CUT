#!/usr/bin/env bash
# end-card: composite a closing CTA banner ("FOLLOW FOR MORE" + @C0BALT_CUT)
# over the LAST `dur` seconds of a finished short, fading in, so the clip ends
# on an intentional beat instead of dead-stopping on a dangling word — the
# "ends abruptly / no loop or CTA" retention fix. TIMELINE-PRESERVING: audio is
# copied untouched and total duration is identical, so it never shifts a
# downstream timestamp. Deterministic (no Claude), non-fatal (failure ->
# passthrough). END_CARD=0 skips.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"

input="${1:-}"
out="${2:-}"
dur="${3:-${END_CARD_DUR:-2.5}}"
line1="${4:-${END_CARD_TEXT:-FOLLOW FOR MORE}}"
line2="${5:-${END_CARD_HANDLE:-@C0BALT_CUT}}"
yfrac="${END_CARD_Y_FRAC:-0.60}"

if [[ -z "$input" || -z "$out" ]]; then
  echo "usage: end-card.sh <in.mp4> <out.mp4> [dur=2.5] [line1] [line2]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "end-card: input not found: $input" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
sig="$(mtime "$input")|$dur|$line1|$line2|$yfrac|${END_CARD:-1}|v1"
meta="$out.ecmeta"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "end-card: cache hit at $out" >&2
  echo "$out"; exit 0
fi
mkdir -p "$(dirname "$out")"

passthrough() {
  ffmpeg -y -hide_banner -loglevel error -i "$input" -c copy "$out" 2>/dev/null || cp "$input" "$out"
  printf '%s' "$sig" > "$meta"; echo "$out"
}

if [[ "${END_CARD:-1}" == "0" ]]; then
  echo "end-card: disabled (END_CARD=0) — passthrough" >&2; passthrough; exit 0
fi

read -r w h < <(ffprobe -v error -select_streams v:0 -show_entries stream=width,height \
  -of default=nw=1:nk=1 "$input" 2>/dev/null | paste -sd' ' -)
vdur="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$input" 2>/dev/null)"
if ! [[ "$w" =~ ^[0-9]+$ && "$h" =~ ^[0-9]+$ ]] || [[ -z "$vdur" ]]; then
  echo "end-card: probe failed — passthrough" >&2; passthrough; exit 0
fi

# clamp dur to the clip; the card holds from `start` to the last frame, fading in.
dur="$(python3 -c "print(round(min(float('$dur'), max(1.0, float('$vdur') - 0.2)), 3))")"
start="$(python3 -c "print(round(max(0.0, float('$vdur') - float('$dur') - 0.05), 3))")"
fade="$(python3 -c "print(round(min(0.4, float('$dur') / 4), 3))")"

ov_y="(H*${yfrac})-(h/2)"

# OVERLAY_PLAN_ONLY: render the end-card PNG to a STABLE sidecar dir and emit a
# base-relative *.overlay.json instead of encoding. The fused compositor applies
# it with the CTA spec in one completion-cluster pass.
if [[ "${OVERLAY_PLAN_ONLY:-0}" != "0" ]]; then
  assets="${out}.assets"
  mkdir -p "$assets"
  if ! python3 "$here/render_endcard.py" "$line1" "$line2" "$assets/endcard.png" "$w" "$h" 2>/dev/null; then
    echo "end-card: plan-only render failed — emitting no-op spec" >&2
    python3 - "$out" <<'PY'
import json, sys
json.dump({"inputs": [], "filter": "[{IN}]null[{OUT}]", "audio": None, "quality": "high"}, open(sys.argv[1], "w"), indent=2)
PY
    printf '%s' "$sig" > "$meta"; echo "$out"; exit 0
  fi
  python3 - "$out" "$assets/endcard.png" "$vdur" "$start" "$fade" "$ov_y" <<'PY'
import json, sys
out, png, vdur, start, fade, ov_y = sys.argv[1:7]
spec = {
  "inputs": [{"path": png, "loop": True, "t": float(vdur)}],
  "filter": (
    "[{L0}]format=rgba,fade=t=in:st=%s:d=%s:alpha=1[ecec];"
    "[{IN}][ecec]overlay=x='(W-w)/2':y='%s':enable='gte(t,%s)':format=auto[{OUT}]"
    % (start, fade, ov_y, start)
  ),
  "audio": None,
  "quality": "high",
}
json.dump(spec, open(out, "w"), indent=2)
PY
  printf '%s' "$sig" > "$meta"
  echo "end-card: plan-only spec -> $out (closing beat last ${dur}s @ y=${yfrac})" >&2
  echo "$out"; exit 0
fi

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
png="$tmp/endcard.png"
python3 "$here/render_endcard.py" "$line1" "$line2" "$png" "$w" "$h" 2>/dev/null \
  || { echo "end-card: render failed — passthrough" >&2; passthrough; exit 0; }

has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$input" 2>/dev/null || true)"
flt="[1:v]format=rgba,fade=t=in:st=${start}:d=${fade}:alpha=1[ec];[0:v][ec]overlay=x='(W-w)/2':y='${ov_y}':enable='gte(t,${start})':format=auto[v]"

declare -a venc thr
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args high)
while IFS= read -r -d '' a; do thr+=("$a"); done < <(vt_threads)
amap=()
[[ "$has_audio" == "audio" ]] && amap=(-map 0:a -c:a copy)

staging="$tmp/$(basename "$out")"
if ! ffmpeg -y -hide_banner -loglevel error \
  -i "$input" -loop 1 -t "$vdur" -i "$png" \
  -filter_complex "$flt" -map "[v]" "${amap[@]+"${amap[@]}"}" \
  "${venc[@]}" "${thr[@]}" -movflags +faststart "$staging" 2>"$tmp/err.log"; then
  echo "end-card: ffmpeg failed — passthrough" >&2; cat "$tmp/err.log" >&2; passthrough; exit 0
fi
mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "end-card: wrote $out (closing beat last ${dur}s @ y=${yfrac})" >&2
echo "$out"
