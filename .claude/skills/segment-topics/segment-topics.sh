#!/usr/bin/env bash
# segment-topics: transcript -> contiguous topical chapters (Claude-driven)
set -euo pipefail

transcript="${1:-}"
out="${2:-}"

if [[ -z "$transcript" ]]; then
  echo "usage: segment-topics.sh <transcript.json> [out.json]" >&2
  exit 2
fi
if [[ ! -f "$transcript" ]]; then
  echo "segment-topics: transcript not found: $transcript" >&2
  exit 2
fi

here="$(cd "$(dirname "$0")" && pwd)"
[[ -z "$out" ]] && out="$(dirname "$transcript")/topics.json"

if [[ -f "$out" ]]; then
  in_mtime="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
  out_mtime="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$out_mtime" -ge "$in_mtime" ]]; then
    echo "segment-topics: cache hit at $out" >&2
    echo "$out"
    exit 0
  fi
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

prompt="$tmp/prompt.txt"
python3 "$here/build_prompt.py" "$transcript" > "$prompt"

reply="$tmp/reply.txt"
claude -p --output-format text < "$prompt" > "$reply" 2>"$tmp/claude.err" || {
  echo "segment-topics: claude -p failed" >&2
  cat "$tmp/claude.err" >&2
  exit 1
}

python3 "$here/parse_reply.py" "$reply" "$transcript" > "$out"
echo "segment-topics: wrote $out" >&2
echo "$out"
