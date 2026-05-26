#!/usr/bin/env bash
# bookend-trim: snap each picked segment's [t0, t1] to a sentence boundary by
# asking claude to pick clean sentence-start / sentence-end timestamps from
# whisper transcript-segment lines in a ±extend window. whisper.cpp in this
# project strips punctuation, so a pure heuristic is unreliable — we delegate
# the inference to claude.
set -euo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

segs="${1:-}"
tx="${2:-}"
out="${3:-}"
extend="${4:-6.0}"
dmin="${5:-20}"

if [[ -z "$segs" || -z "$tx" || -z "$out" ]]; then
  echo "usage: bookend-trim.sh <segments.json> <transcript.json> <out.json> [extend=6.0] [dmin=20]" >&2
  exit 2
fi
[[ -f "$segs" ]] || { echo "bookend-trim: segments not found: $segs" >&2; exit 2; }
[[ -f "$tx" ]] || { echo "bookend-trim: transcript not found: $tx" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$(dirname "$out")"

if [[ -f "$out" ]]; then
  s_m="$(stat -f %m "$segs" 2>/dev/null || stat -c %Y "$segs")"
  t_m="$(stat -f %m "$tx" 2>/dev/null || stat -c %Y "$tx")"
  o_m="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$o_m" -ge "$s_m" && "$o_m" -ge "$t_m" ]]; then
    echo "bookend-trim: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["shorts"]))' "$segs")"
if [[ "$count" -eq 0 ]]; then
  cp "$segs" "$out"
  echo "bookend-trim: no spans; passthrough" >&2
  echo "$out"; exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/build_prompt.py" "$segs" "$tx" "$extend" > "$tmp/prompt.txt"

run_claude_step bookend-trim "$tmp/prompt.txt" "$tmp/reply.txt" 2>"$tmp/claude.err" || {
  echo "bookend-trim: claude step failed" >&2
  cat "$tmp/claude.err" >&2
  exit 1
}

python3 "$here/parse_reply.py" "$tmp/reply.txt" "$segs" "$extend" "$dmin" > "$out"

echo "bookend-trim: wrote $out ($count span(s))" >&2
echo "$out"
