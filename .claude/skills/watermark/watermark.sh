#!/usr/bin/env bash
# watermark: overlay the persistent @C0BALT_CUT channel mark at the BOTTOM
# of the frame — vertical opposite of source-credit's top banner.
set -euo pipefail

input="${1:-}"
out="${2:-}"

if [[ -z "$input" || -z "$out" ]]; then
  echo "usage: watermark.sh <input> <out>" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "watermark: input not found: $input" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"

if [[ -f "$out" ]]; then
  o="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  i="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  if [[ "$o" -ge "$i" ]]; then
    echo "watermark: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

read -r w h < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height -of default=nw=1:nk=1 "$input" | paste -sd' ' -)
[[ "$w" =~ ^[0-9]+$ && "$h" =~ ^[0-9]+$ ]] || {
  echo "watermark: could not read video dimensions" >&2; exit 1; }

has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$input" 2>/dev/null || true)"

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/render_watermark.py" "$tmp/mark.png" "$w" "$h"

# Center horizontally; bottom-anchor at ~97.5% of frame height. Sits below
# the lower-third captions; the CTA overlay (last ~4s) composites on top.
ov="[0:v][1:v]overlay=x='(W-w)/2':y='H*0.975-h':format=auto[v]"

staging="$tmp/$(basename "$out")"

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

if [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -i "$tmp/mark.png" \
    -filter_complex "${ov}" \
    -map "[v]" -map 0:a \
    "${venc[@]}" \
    -c:a copy "${vthr[@]}" -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -i "$tmp/mark.png" \
    -filter_complex "${ov}" \
    -map "[v]" \
    "${venc[@]}" \
    "${vthr[@]}" -movflags +faststart "$staging"
fi

mv "$staging" "$out"
echo "watermark: wrote $out  ${w}x${h}" >&2
echo "$out"
