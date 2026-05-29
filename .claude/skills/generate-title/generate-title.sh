#!/usr/bin/env bash
# generate-title: clip transcript + ingest metadata -> ALL-CAPS <=7-word title.
set -euo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

transcript="${1:-}"
ingest="${2:-}"
out="${3:-}"
# Optional: pick-segments' semantic judgment for this span (topic, rationale,
# suggested title). Gives the model the surrounding context the clip-local
# transcript alone can't carry — so it reads tone/irony, not just the words.
ctx="${4:-}"

if [[ -z "$transcript" || -z "$ingest" || -z "$out" ]]; then
  echo "usage: generate-title.sh <clip_transcript.json> <ingest.json> <out.txt> [title-context.json]" >&2
  exit 2
fi
[[ -f "$transcript" ]] || { echo "generate-title: transcript not found: $transcript" >&2; exit 2; }
[[ -f "$ingest" ]]     || { echo "generate-title: ingest not found: $ingest" >&2; exit 2; }
[[ -n "$ctx" && ! -f "$ctx" ]] && { echo "generate-title: context not found, ignoring: $ctx" >&2; ctx=""; }

here="$(cd "$(dirname "$0")" && pwd)"

if [[ -f "$out" ]]; then
  i_m="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
  g_m="$(stat -f %m "$ingest" 2>/dev/null || stat -c %Y "$ingest")"
  o_m="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  c_m=0
  [[ -n "$ctx" ]] && c_m="$(stat -f %m "$ctx" 2>/dev/null || stat -c %Y "$ctx")"
  if [[ "$o_m" -ge "$i_m" && "$o_m" -ge "$g_m" && "$o_m" -ge "$c_m" ]]; then
    echo "generate-title: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

prompt="$tmp/prompt.txt"
python3 "$here/build_prompt.py" "$transcript" "$ingest" "$ctx" > "$prompt"

reply="$tmp/reply.txt"
if ! run_claude_step generate-title "$prompt" "$reply" 2>"$tmp/claude.err"; then
  echo "generate-title: claude step failed; using fallback" >&2
  cat "$tmp/claude.err" >&2
  : > "$reply"
fi

python3 "$here/parse_reply.py" "$reply" "$transcript" > "$out"
title="$(cat "$out")"
echo "generate-title: wrote $out  title=\"$title\"" >&2
echo "$out"
