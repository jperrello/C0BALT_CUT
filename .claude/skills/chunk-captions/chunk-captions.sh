#!/usr/bin/env bash
# chunk-captions: clip transcript -> phrase-sized caption chunks (Claude-driven)
set -euo pipefail

transcript="${1:-}"
out="${2:-}"

if [[ -z "$transcript" || -z "$out" ]]; then
  echo "usage: chunk-captions.sh <clip_transcript.json> <out.json>" >&2
  exit 2
fi
[[ -f "$transcript" ]] || { echo "chunk-captions: not found: $transcript" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"

if [[ -f "$out" ]]; then
  i_m="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
  o_m="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$o_m" -ge "$i_m" ]]; then
    echo "chunk-captions: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

nwords="$(python3 -c 'import json,sys; print(len([w for w in json.load(open(sys.argv[1])).get("words",[]) if str(w.get("w","")).strip()]))' "$transcript")"
if [[ "$nwords" -eq 0 ]]; then
  echo '{"chunks":[]}' > "$out"
  echo "chunk-captions: no words; empty chunks" >&2
  echo "$out"; exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

prompt="$tmp/prompt.txt"
python3 "$here/build_prompt.py" "$transcript" > "$prompt"

reply="$tmp/reply.txt"
if ! claude -p --output-format text < "$prompt" > "$reply" 2>"$tmp/claude.err"; then
  echo "chunk-captions: claude -p failed; using fallback" >&2
  cat "$tmp/claude.err" >&2
  : > "$reply"
fi

python3 "$here/parse_reply.py" "$reply" "$transcript" > "$out"
echo "chunk-captions: wrote $out  words=$nwords" >&2
echo "$out"
