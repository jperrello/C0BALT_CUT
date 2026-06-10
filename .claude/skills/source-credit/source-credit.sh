#!/usr/bin/env bash
# source-credit: overlay a persistent "Original video: <title>" banner on
# the bottom third of a clip. PNG rendered via PIL, composited by ffmpeg.
set -euo pipefail

input="${1:-}"
ingest="${2:-}"
out="${3:-}"

if [[ -z "$input" || -z "$ingest" || -z "$out" ]]; then
  echo "usage: source-credit.sh <input> <ingest.json> <out>" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "source-credit: input not found: $input" >&2; exit 2; }
[[ -f "$ingest" ]] || { echo "source-credit: ingest.json not found: $ingest" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"

title="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print((d.get("title") or d.get("id") or d.get("source_id") or "Unknown").strip())
' "$ingest")"
[[ -n "$title" ]] || title="Unknown"

meta="$out.scmeta"
sig="$title"

if [[ -f "$out" && -f "$meta" ]]; then
  o="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  i="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  if [[ "$o" -ge "$i" && "$(cat "$meta")" == "$sig" ]]; then
    echo "source-credit: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

read -r w h < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height -of default=nw=1:nk=1 "$input" | paste -sd' ' -)
[[ "$w" =~ ^[0-9]+$ && "$h" =~ ^[0-9]+$ ]] || {
  echo "source-credit: could not read video dimensions" >&2; exit 1; }

has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$input" 2>/dev/null || true)"

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/render_credit.py" "$title" "$tmp/credit.png" "$w" "$h"

# Center horizontally; anchor banner near the TOP of the frame.
# For 1080x1920 -> y≈77. Sits above the captions (now in the lower third)
# and clear of the centered title card.
ov="[0:v][1:v]overlay=x='(W-w)/2':y='H*0.04':format=auto[v]"

staging="$tmp/$(basename "$out")"

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

if [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -i "$tmp/credit.png" \
    -filter_complex "${ov}" \
    -map "[v]" -map 0:a \
    "${venc[@]}" \
    -c:a copy "${vthr[@]}" -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -i "$tmp/credit.png" \
    -filter_complex "${ov}" \
    -map "[v]" \
    "${venc[@]}" \
    "${vthr[@]}" -movflags +faststart "$staging"
fi

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "source-credit: wrote $out  ${w}x${h}  title=\"$title\"" >&2
echo "$out"
