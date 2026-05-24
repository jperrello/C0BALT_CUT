#!/usr/bin/env bash
# verify-coherence: post-pick gate that tightens incoherent spans.
set -euo pipefail

segments="${1:-}"
transcript="${2:-}"
out="${3:-}"
dmin="${4:-20}"

if [[ -z "$segments" || -z "$transcript" || -z "$out" ]]; then
  echo "usage: verify-coherence.sh <segments.json> <transcript.json> <out.json> [dmin=20]" >&2
  exit 2
fi
for f in "$segments" "$transcript"; do
  [[ -f "$f" ]] || { echo "verify-coherence: not found: $f" >&2; exit 2; }
done

here="$(cd "$(dirname "$0")" && pwd)"

if [[ -f "$out" ]]; then
  s_m="$(stat -f %m "$segments" 2>/dev/null || stat -c %Y "$segments")"
  t_m="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
  o_m="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$o_m" -ge "$s_m" && "$o_m" -ge "$t_m" ]]; then
    echo "verify-coherence: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["shorts"]))' "$segments")"
if [[ "$count" -eq 0 ]]; then
  cp "$segments" "$out"
  echo "verify-coherence: no spans to verify; passthrough" >&2
  echo "$out"; exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

prompt="$tmp/prompt.txt"
python3 "$here/build_prompt.py" "$segments" "$transcript" > "$prompt"

reply="$tmp/reply.txt"
claude -p --output-format text < "$prompt" > "$reply" 2>"$tmp/claude.err" || {
  echo "verify-coherence: claude -p failed" >&2
  cat "$tmp/claude.err" >&2
  exit 1
}

python3 "$here/parse_reply.py" "$reply" "$segments" "$dmin" > "$out"
echo "verify-coherence: wrote $out" >&2
echo "$out"
