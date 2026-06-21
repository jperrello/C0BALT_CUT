#!/usr/bin/env bash
# verify-completeness: arc-completeness gate. Reads each picked span's ASSEMBLED
# arc (the words inside its cuts) plus a tail lookahead and asks claude whether
# the short LANDS as a standalone story. When the payoff is cut off but recoverable
# in the immediate source tail, it nudges t1 (and the last cut's end) OUTWARD to
# the landing sentence — within dmax. The outward counterpart to verify-bookends
# (which is inward-only, post-cut). Runs after bookend-trim, before cut-clip, in
# SOURCE coordinates (the only place outward extension is clean — the clip-local
# transcript discards source times after cut/trim/tighten).
#
# Non-fatal: any claude/parse failure passes segments through unchanged.
# Disable with VERIFY_COMPLETENESS=0.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

segs="${1:-}"
tx="${2:-}"
out="${3:-}"
dmax="${4:-55}"

if [[ -z "$segs" || -z "$tx" || -z "$out" ]]; then
  echo "usage: verify-completeness.sh <segments.json> <transcript.json> <out.json> [dmax=55]" >&2
  exit 2
fi
[[ -f "$segs" ]] || { echo "verify-completeness: segments not found: $segs" >&2; exit 2; }
[[ -f "$tx" ]] || { echo "verify-completeness: transcript not found: $tx" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$(dirname "$out")"

if [[ "${VERIFY_COMPLETENESS:-1}" == "0" ]]; then
  cp "$segs" "$out"
  echo "verify-completeness: disabled (VERIFY_COMPLETENESS=0); passthrough" >&2
  echo "$out"; exit 0
fi

# idempotent: skip when out is newer than both inputs
if [[ -f "$out" ]]; then
  s_m="$(stat -f %m "$segs" 2>/dev/null || stat -c %Y "$segs")"
  t_m="$(stat -f %m "$tx" 2>/dev/null || stat -c %Y "$tx")"
  o_m="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$o_m" -ge "$s_m" && "$o_m" -ge "$t_m" ]]; then
    echo "verify-completeness: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["shorts"]))' "$segs" 2>/dev/null || echo 0)"
if [[ "$count" -eq 0 ]]; then
  cp "$segs" "$out"
  echo "verify-completeness: no spans; passthrough" >&2
  echo "$out"; exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/build_prompt.py" "$segs" "$tx" "$dmax" > "$tmp/prompt.txt"

if ! run_claude_step verify-completeness "$tmp/prompt.txt" "$tmp/reply.txt" 2>"$tmp/claude.err"; then
  echo "verify-completeness: claude step failed; passthrough" >&2
  cat "$tmp/claude.err" >&2
  cp "$segs" "$out"
  echo "$out"; exit 0
fi

if ! python3 "$here/parse_reply.py" "$tmp/reply.txt" "$segs" "$dmax" "$tx" > "$out" 2>"$tmp/parse.err"; then
  echo "verify-completeness: parse failed; passthrough" >&2
  cat "$tmp/parse.err" >&2
  cp "$segs" "$out"
  echo "$out"; exit 0
fi

python3 - "$out" >&2 <<'PY' || true
import json,sys
d=json.load(open(sys.argv[1]))
for i,s in enumerate(d["shorts"]):
    print(f"  span {i}: {s.get('completeness_verdict','?')} — {s.get('completeness_note','')}")
PY

echo "verify-completeness: wrote $out ($count span(s))" >&2
echo "$out"
