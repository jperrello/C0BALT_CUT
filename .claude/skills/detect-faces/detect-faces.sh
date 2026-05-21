#!/usr/bin/env bash
# detect-faces: sample frames at <fps> and emit face bounding boxes JSON.
set -euo pipefail

input="${1:-}"
out="${2:-}"
fps="${3:-5}"

if [[ -z "$input" ]]; then
  echo "usage: detect-faces.sh <input> [out] [fps]" >&2
  exit 2
fi
if [[ ! -f "$input" ]]; then
  echo "detect-faces: input not found: $input" >&2
  exit 2
fi

if [[ -z "$out" ]]; then
  out="${input}.faces.json"
fi

here="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$here/detect_faces.py" "$input" --fps "$fps" --out "$out"
