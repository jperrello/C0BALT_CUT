#!/usr/bin/env bash
# pick-segments: transcript + audio energy -> N clip-worthy spans (Claude-driven)
set -euo pipefail

transcript="${1:-}"
out="${2:-}"
n="${3:-5}"
dmin="${4:-20}"
dmax="${5:-60}"

if [[ -z "$transcript" ]]; then
  echo "usage: pick-segments.sh <transcript.json> [out.json] [n=5] [dmin=20] [dmax=60]" >&2
  exit 2
fi
if [[ ! -f "$transcript" ]]; then
  echo "pick-segments: transcript not found: $transcript" >&2
  exit 2
fi

here="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "$out" ]]; then
  out="$(dirname "$transcript")/segments.json"
fi

if [[ -f "$out" ]]; then
  in_mtime="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
  out_mtime="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$out_mtime" -ge "$in_mtime" ]]; then
    echo "pick-segments: cache hit at $out" >&2
    exit 0
  fi
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Derive source media path from transcript "source" field
src="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("source",""))' "$transcript")"
rms_json="$tmp/rms.json"
if [[ -n "$src" && -f "$src" ]]; then
  python3 "$here/rms.py" "$src" > "$rms_json"
else
  echo '{"fps":1,"seconds":0,"min":0,"max":0,"mean":0,"rms":[]}' > "$rms_json"
fi

prompt_file="$tmp/prompt.txt"
python3 "$here/build_prompt.py" "$transcript" "$rms_json" "$n" "$dmin" "$dmax" > "$prompt_file"

reply="$tmp/reply.txt"
claude -p --output-format text < "$prompt_file" > "$reply" 2>"$tmp/claude.err" || {
  echo "pick-segments: claude -p failed" >&2
  cat "$tmp/claude.err" >&2
  exit 1
}

python3 "$here/parse_reply.py" "$reply" "$n" "$dmin" "$dmax" "$transcript" > "$out"
echo "pick-segments: wrote $out" >&2
echo "$out"
