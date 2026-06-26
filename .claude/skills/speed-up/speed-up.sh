#!/usr/bin/env bash
# speed-up: globally retime a finished short by SPEED (default 1.15x) — the LAST
# step of the per-span edit chain. Video is retimed with setpts=PTS/SPEED and
# audio with atempo=SPEED (pitch-corrected), so every relative beat (captions,
# zoom punches, b-roll windows, CTA, end-card) compresses uniformly and stays in
# sync. Deterministic (no Claude), non-fatal (failure -> passthrough). SPEED=1
# (or SPEED_UP=0) is a passthrough copy.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"

input="${1:-}"
out="${2:-}"
speed="${3:-${SPEED:-1.15}}"

if [[ -z "$input" || -z "$out" ]]; then
  echo "usage: speed-up.sh <in.mp4> <out.mp4> [speed=1.15]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "speed-up: input not found: $input" >&2; exit 2; }

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
sig="$(mtime "$input")|$speed|${SPEED_UP:-1}|v1"
meta="$out.spmeta"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "speed-up: cache hit at $out" >&2
  echo "$out"; exit 0
fi
mkdir -p "$(dirname "$out")"

passthrough() {
  ffmpeg -y -hide_banner -loglevel error -i "$input" -c copy "$out" 2>/dev/null || cp "$input" "$out"
  printf '%s' "$sig" > "$meta"; echo "$out"
}

# SPEED_UP=0 disables; speed==1 is a no-op.
if [[ "${SPEED_UP:-1}" == "0" ]] || python3 -c "import sys;sys.exit(0 if abs(float('$speed')-1.0)<1e-3 else 1)"; then
  echo "speed-up: disabled / speed=1 — passthrough" >&2; passthrough; exit 0
fi

# atempo accepts 0.5-2.0 per stage; chain stages for out-of-range speeds.
atempo="$(python3 -c "
s=float('$speed'); out=[]
while s>2.0: out.append('atempo=2.0'); s/=2.0
while s<0.5: out.append('atempo=0.5'); s/=0.5
out.append('atempo=%g'%s)
print(','.join(out))
")"

has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$input" 2>/dev/null || true)"

declare -a venc thr
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args high)
while IFS= read -r -d '' a; do thr+=("$a"); done < <(vt_threads)

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
staging="$tmp/$(basename "$out")"

if [[ "$has_audio" == "audio" ]]; then
  ok=1
  ffmpeg -y -hide_banner -loglevel error -i "$input" \
    -filter_complex "[0:v]setpts=PTS/${speed}[v];[0:a]${atempo}[a]" \
    -map "[v]" -map "[a]" -c:a aac -b:a 192k \
    "${venc[@]}" "${thr[@]}" -movflags +faststart "$staging" 2>"$tmp/err.log" || ok=0
else
  ok=1
  ffmpeg -y -hide_banner -loglevel error -i "$input" \
    -filter_complex "[0:v]setpts=PTS/${speed}[v]" -map "[v]" \
    "${venc[@]}" "${thr[@]}" -movflags +faststart "$staging" 2>"$tmp/err.log" || ok=0
fi

if [[ "$ok" != "1" ]]; then
  echo "speed-up: ffmpeg failed — passthrough" >&2; cat "$tmp/err.log" >&2; passthrough; exit 0
fi
mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "speed-up: wrote $out (${speed}x retime)" >&2
echo "$out"
