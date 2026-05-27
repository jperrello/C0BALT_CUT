#!/usr/bin/env bash
# fit-vertical: reframe a horizontal video to 9:16 with a blurred background
set -euo pipefail

input="${1:-}"
out="${2:-}"
target="${3:-1080x1920}"
sigma="${4:-20}"

if [[ -z "$input" || -z "$out" ]]; then
  echo "usage: fit-vertical.sh <input> <out> [target=1080x1920] [blur_sigma=20]" >&2
  exit 2
fi
if [[ ! -f "$input" ]]; then
  echo "fit-vertical: input not found: $input" >&2
  exit 2
fi

w="${target%x*}"
h="${target#*x}"
if [[ -z "$w" || -z "$h" || "$w" == "$target" ]]; then
  echo "fit-vertical: bad target '$target' (expected WxH, e.g. 1080x1920)" >&2
  exit 2
fi

if [[ -f "$out" ]]; then
  in_mtime="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  out_mtime="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$out_mtime" -ge "$in_mtime" ]]; then
    echo "fit-vertical: cache hit at $out" >&2
    exit 0
  fi
fi

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
staging="$tmp/$(basename "$out")"

# bg: zoom-crop to cover the frame, then gaussian blur.
# fg: scale to fit inside the frame untouched, centered over the bg.
filter="[0:v]split=2[bg][fg];\
[bg]scale=${w}:${h}:force_original_aspect_ratio=increase,crop=${w}:${h},gblur=sigma=${sigma}[bgb];\
[fg]scale=${w}:${h}:force_original_aspect_ratio=decrease[fgs];\
[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args low)
while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

ffmpeg -y -hide_banner -loglevel error \
  ${vdec[@]+"${vdec[@]}"} -i "$input" \
  -filter_complex "$filter" \
  -map "[v]" -map 0:a? \
  "${venc[@]}" \
  -c:a copy \
  "${vthr[@]}" -movflags +faststart \
  "$staging"

mv "$staging" "$out"
echo "fit-vertical: wrote $out (${w}x${h})" >&2
