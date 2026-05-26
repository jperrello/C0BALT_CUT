#!/usr/bin/env bash
# trim-filler: Claude marks filler/trail-offs/asides in a clip transcript;
# emits keeps.json + transcript.trimmed.json. Pairs with cut-filler.
set -euo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

in_tx="${1:-}"
out_keeps="${2:-}"
out_tx="${3:-}"
pad="${4:-0.05}"

if [[ -z "$in_tx" || -z "$out_keeps" || -z "$out_tx" ]]; then
  echo "usage: trim-filler.sh <in_transcript> <out_keeps> <out_transcript> [pad=0.05]" >&2
  exit 2
fi
[[ -f "$in_tx" ]] || { echo "trim-filler: transcript not found: $in_tx" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
meta="$out_keeps.tfmeta"
tx_mtime="$(stat -f %m "$in_tx" 2>/dev/null || stat -c %Y "$in_tx")"
sig="$tx_mtime|$pad"

if [[ -f "$out_keeps" && -f "$out_tx" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "trim-filler: cache hit at $out_keeps" >&2
  echo "$out_keeps"; exit 0
fi

n_words="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("words",[])))' "$in_tx")"
mkdir -p "$(dirname "$out_keeps")" "$(dirname "$out_tx")"

if [[ "$n_words" -lt 2 ]]; then
  echo "trim-filler: too few words ($n_words), pass-through" >&2
  python3 -c '
import json,sys
tx=json.load(open(sys.argv[1]))
words=tx.get("words",[])
keeps={"source":sys.argv[1],"keeps":[[words[0]["t0"], words[-1]["t1"]]] if words else [],"removed":[],"removed_total":0.0,"notes":"too few words"}
json.dump(keeps, open(sys.argv[2],"w"))
json.dump(tx, open(sys.argv[3],"w"))
' "$in_tx" "$out_keeps" "$out_tx"
  printf '%s' "$sig" > "$meta"
  echo "$out_keeps"; exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/build_prompt.py" "$in_tx" > "$tmp/prompt.txt"

run_claude_step trim-filler "$tmp/prompt.txt" "$tmp/reply.txt" 2>"$tmp/claude.err" || {
  echo "trim-filler: claude step failed" >&2
  cat "$tmp/claude.err" >&2
  exit 1
}

python3 "$here/parse_reply.py" "$tmp/reply.txt" "$in_tx" "$pad" > "$tmp/combined.json"

python3 -c '
import json,sys
c=json.load(open(sys.argv[1]))
json.dump(c["keeps"], open(sys.argv[2],"w"))
json.dump(c["transcript"], open(sys.argv[3],"w"))
removed=c["keeps"].get("removed_total",0.0)
n=len(c["keeps"].get("removed",[]))
print(f"trim-filler: removed {n} span(s), ~{removed}s", file=sys.stderr)
' "$tmp/combined.json" "$out_keeps" "$out_tx"

printf '%s' "$sig" > "$meta"
echo "$out_keeps"
