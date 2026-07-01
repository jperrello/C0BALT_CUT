#!/usr/bin/env bash
# derive-thesis: topics + transcript -> thesis.json (the source's central subject/
# spine). The theme prior pick-segments scores each pick against. Non-fatal,
# idempotent. DERIVE_THESIS=0 skips.
set -euo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

transcript="${1:-}"
topics="${2:-}"
out="${3:-}"

if [[ -z "$transcript" ]]; then
  echo "usage: derive-thesis.sh <transcript.json> [topics.json] [out.json]" >&2
  exit 2
fi
[[ -z "$topics" ]] && topics="$(dirname "$transcript")/topics.json"
[[ -z "$out" ]] && out="$(dirname "$transcript")/thesis.json"

if [[ "${DERIVE_THESIS:-1}" == "0" ]]; then
  echo "derive-thesis: disabled (DERIVE_THESIS=0)" >&2
  exit 0
fi
for f in "$transcript" "$topics"; do
  [[ -f "$f" ]] || { echo "derive-thesis: not found: $f — skipping (non-fatal)" >&2; exit 0; }
done

here="$(cd "$(dirname "$0")" && pwd)"

if [[ -f "$out" ]]; then
  in_mtime="$(stat -f %m "$topics" 2>/dev/null || stat -c %Y "$topics")"
  out_mtime="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$out_mtime" -ge "$in_mtime" ]]; then
    echo "derive-thesis: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/build_prompt.py" "$transcript" "$topics" > "$tmp/prompt.txt"

reply="$tmp/reply.txt"
if run_claude_step derive-thesis "$tmp/prompt.txt" "$reply" 2>"$tmp/claude.err" \
   && python3 "$here/parse_reply.py" "$reply" "$topics" > "$tmp/thesis.json" 2>"$tmp/parse.err"; then
  mv "$tmp/thesis.json" "$out"
else
  echo "derive-thesis: claude/parse failed; writing deterministic fallback" >&2
  cat "$tmp/claude.err" "$tmp/parse.err" 2>/dev/null >&2 || true
  # /dev/null reply -> parse_reply emits the topic-derived fallback thesis.
  python3 "$here/parse_reply.py" /dev/null "$topics" > "$out" 2>/dev/null || {
    echo "derive-thesis: fallback failed — skipping (non-fatal)" >&2
    exit 0
  }
fi
echo "derive-thesis: wrote $out" >&2
echo "$out"
