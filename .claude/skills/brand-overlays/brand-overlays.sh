#!/usr/bin/env bash
# brand-overlays: composite BOTH persistent brand PNGs — the top
# "Original video: <title>" credit (y≈4%) and the bottom @C0BALT_CUT
# watermark (y≈97.5%) — in ONE ffmpeg pass. Same pixels as running
# source-credit then watermark, minus one full re-encode and one
# intermediate .mp4 per span. The PNGs come from those skills' renderers,
# which stay the single source of truth for type/color/layout.
set -euo pipefail

input="${1:-}"
ingest="${2:-}"
out="${3:-}"

if [[ -z "$input" || -z "$ingest" || -z "$out" ]]; then
  echo "usage: brand-overlays.sh <input> <ingest.json> <out>" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "brand-overlays: input not found: $input" >&2; exit 2; }
[[ -f "$ingest" ]] || { echo "brand-overlays: ingest.json not found: $ingest" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"

title="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print((d.get("title") or d.get("id") or d.get("source_id") or "Unknown").strip())
' "$ingest")"
[[ -n "$title" ]] || title="Unknown"

meta="$out.bometa"
sig="$title"

if [[ -f "$out" && -f "$meta" ]]; then
  o="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  i="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  if [[ "$o" -ge "$i" && "$(cat "$meta")" == "$sig" ]]; then
    echo "brand-overlays: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

read -r w h < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height -of default=nw=1:nk=1 "$input" | paste -sd' ' -)
[[ "$w" =~ ^[0-9]+$ && "$h" =~ ^[0-9]+$ ]] || {
  echo "brand-overlays: could not read video dimensions" >&2; exit 1; }

has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$input" 2>/dev/null || true)"

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/../source-credit/render_credit.py" "$title" "$tmp/credit.png" "$w" "$h"
python3 "$here/../watermark/render_watermark.py" "$tmp/mark.png" "$w" "$h"

# Same placements as the standalone skills: credit top chyron at y≈4%,
# watermark bottom-anchored at y≈97.5% — one overlay chain, one encode.
ov="[0:v][1:v]overlay=x='(W-w)/2':y='H*0.04':format=auto[v1];[v1][2:v]overlay=x='(W-w)/2':y='H*0.975-h':format=auto[v]"

staging="$tmp/$(basename "$out")"

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

if [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -i "$tmp/credit.png" -i "$tmp/mark.png" \
    -filter_complex "${ov}" \
    -map "[v]" -map 0:a \
    "${venc[@]}" \
    -c:a copy "${vthr[@]}" -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -i "$tmp/credit.png" -i "$tmp/mark.png" \
    -filter_complex "${ov}" \
    -map "[v]" \
    "${venc[@]}" \
    "${vthr[@]}" -movflags +faststart "$staging"
fi

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "brand-overlays: wrote $out  ${w}x${h}  title=\"$title\"" >&2
echo "$out"
