#!/usr/bin/env bash
# pick-segments: transcript + audio energy -> N clip-worthy spans (Claude-driven)
set -euo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

transcript="${1:-}"
out="${2:-}"
n="${3:-5}"
dmin="${4:-20}"
dmax="${5:-60}"
topics="${6:-}"

if [[ -z "$transcript" ]]; then
  echo "usage: pick-segments.sh <transcript.json> [out.json] [n=5] [dmin=20] [dmax=60] [topics.json]" >&2
  exit 2
fi
# Auto-discover topics.json next to the transcript if not passed
if [[ -z "$topics" ]]; then
  cand="$(dirname "$transcript")/topics.json"
  [[ -f "$cand" ]] && topics="$cand"
fi
# Replay heatmap (most-replayed graph captured by ingest) — engagement prior
heatmap=""
hm_cand="$(dirname "$transcript")/heatmap.json"
[[ -f "$hm_cand" ]] && heatmap="$hm_cand"
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
  if [[ -n "$topics" && -f "$topics" ]]; then
    tp_mtime="$(stat -f %m "$topics" 2>/dev/null || stat -c %Y "$topics")"
    [[ "$tp_mtime" -gt "$in_mtime" ]] && in_mtime="$tp_mtime"
  fi
  if [[ -n "$heatmap" ]]; then
    hm_mtime="$(stat -f %m "$heatmap" 2>/dev/null || stat -c %Y "$heatmap")"
    [[ "$hm_mtime" -gt "$in_mtime" ]] && in_mtime="$hm_mtime"
  fi
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
python3 "$here/build_prompt.py" "$transcript" "$rms_json" "$n" "$dmin" "$dmax" "${topics:-}" "${heatmap:-}" > "$prompt_file"

reply="$tmp/reply.txt"
run_claude_step pick-segments "$prompt_file" "$reply" 2>"$tmp/claude.err" || {
  echo "pick-segments: claude step failed" >&2
  cat "$tmp/claude.err" >&2
  exit 1
}

python3 "$here/parse_reply.py" "$reply" "$n" "$dmin" "$dmax" "$transcript" "${topics:-}" "${heatmap:-}" > "$out"
echo "pick-segments: wrote $out" >&2
echo "$out"
