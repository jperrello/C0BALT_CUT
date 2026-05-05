#!/usr/bin/env bash
# fetch_sources.sh — pull the three eval VODs into source/ with deterministic names.
# Per CONTEXT.md D-08. Idempotent: skips a VOD if its target file already exists.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/source"
mkdir -p "$DEST"

VODS=(
  "vod-tyler1-jynxzi.mp4|u7OUP9b6MCM"
  "vod-medium.mp4|2R5bqqVF2a4"
  "vod-podcast.mp4|-_6mni6k0Zw"
)

FORMAT='bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4]'

for entry in "${VODS[@]}"; do
  name="${entry%%|*}"
  id="${entry##*|}"
  out="$DEST/$name"
  if [[ -f "$out" ]]; then
    echo "[skip] $name already present"
    continue
  fi
  echo "[fetch] $name <- https://www.youtube.com/watch?v=$id"
  yt-dlp \
    -f "$FORMAT" \
    --merge-output-format mp4 \
    -o "$out" \
    "https://www.youtube.com/watch?v=$id"
done

echo "[done] eval VODs in $DEST"
