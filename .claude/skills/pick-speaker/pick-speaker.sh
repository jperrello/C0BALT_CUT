#!/usr/bin/env bash
# pick-speaker: transcript + faces -> per-segment active-speaker box track
set -euo pipefail

transcript="${1:-}"
faces="${2:-}"
video="${3:-}"
out="${4:-}"

if [[ -z "$transcript" || -z "$faces" ]]; then
  echo "usage: pick-speaker.sh <transcript.json> <faces.json> [video] [out.json]" >&2
  exit 2
fi
for f in "$transcript" "$faces"; do
  [[ -f "$f" ]] || { echo "pick-speaker: not found: $f" >&2; exit 2; }
done

here="$(cd "$(dirname "$0")" && pwd)"
args=("$transcript" "$faces")
[[ -n "$video" ]] && args+=("$video")
[[ -n "$out" ]] && args+=(--out "$out")

exec python3 "$here/pick_speaker.py" "${args[@]}"
