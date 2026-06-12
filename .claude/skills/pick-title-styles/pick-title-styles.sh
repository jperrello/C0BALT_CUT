#!/usr/bin/env bash
# pick-title-styles: one batched Claude call assigns a title-transition style
# to every picked span (fit first, variety as tiebreak). writes title_style +
# title_style_note into each span. non-fatal by design: any failure degrades
# to a deterministic least-recently-used round-robin, never an error exit.
set -euo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

segments="${1:-}"
transcript="${2:-}"
out="${3:-}"

if [[ -z "$segments" || -z "$transcript" || -z "$out" ]]; then
  echo "usage: pick-title-styles.sh <segments.json> <transcript.json> <out.json>" >&2
  exit 2
fi
for f in "$segments" "$transcript"; do
  [[ -f "$f" ]] || { echo "pick-title-styles: not found: $f" >&2; exit 2; }
done

here="$(cd "$(dirname "$0")" && pwd)"
recent="$here/.recent"

# idempotence: skip when every span already carries a title_style (mtime is
# useless here — out may BE the segments file, updated in place).
if python3 -c '
import json, sys
segs = json.load(open(sys.argv[1])).get("shorts", [])
sys.exit(0 if segs and all("title_style" in s for s in segs) else 1)' "$segments" 2>/dev/null; then
  [[ "$segments" == "$out" ]] || cp "$segments" "$out"
  echo "pick-title-styles: cache hit (all spans styled)" >&2
  echo "$out"; exit 0
fi

count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["shorts"]))' "$segments")"
if [[ "$count" -eq 0 ]]; then
  [[ "$segments" == "$out" ]] || cp "$segments" "$out"
  echo "pick-title-styles: no spans; passthrough" >&2
  echo "$out"; exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

prompt="$tmp/prompt.txt"
python3 "$here/build_prompt.py" "$segments" "$transcript" "$recent" > "$prompt"

reply="$tmp/reply.txt"
if ! run_claude_step pick-title-styles "$prompt" "$reply" 2>"$tmp/claude.err"; then
  echo "pick-title-styles: claude step failed — deterministic fallback" >&2
  cat "$tmp/claude.err" >&2 || true
  : > "$reply"
fi

python3 "$here/parse_reply.py" "$reply" "$segments" "$recent" > "$tmp/out.json"
mv "$tmp/out.json" "$out"
echo "pick-title-styles: wrote $out" >&2
echo "$out"
