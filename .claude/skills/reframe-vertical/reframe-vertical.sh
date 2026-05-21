#!/usr/bin/env bash
# reframe-vertical: speaker-tracked 9:16 crop
set -euo pipefail

input="${1:-}"
track="${2:-}"
out="${3:-}"
target="${4:-1080x1920}"

if [[ -z "$input" || -z "$track" || -z "$out" ]]; then
  echo "usage: reframe-vertical.sh <input> <speaker_track.json> <out> [target=1080x1920]" >&2
  exit 2
fi
for f in "$input" "$track"; do
  [[ -f "$f" ]] || { echo "reframe-vertical: not found: $f" >&2; exit 2; }
done

if [[ -f "$out" ]]; then
  o="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  i="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  t="$(stat -f %m "$track" 2>/dev/null || stat -c %Y "$track")"
  if [[ "$o" -ge "$i" && "$o" -ge "$t" ]]; then
    echo "reframe-vertical: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

here="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$here/reframe_vertical.py" "$input" "$track" "$out" --target "$target"
