#!/usr/bin/env bash
# pick-mood: clip transcript -> chosen ./songs/<mood>/ folder name.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

transcript="${1:-}"
out="${2:-}"

if [[ -z "$transcript" || -z "$out" ]]; then
  echo "usage: pick-mood.sh <clip_transcript.json> <out.txt>" >&2
  exit 2
fi
[[ -f "$transcript" ]] || { echo "pick-mood: transcript not found: $transcript" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
songs_root="$root/songs"
[[ -d "$songs_root" ]] || { echo "pick-mood: songs root not found: $songs_root" >&2; echo "ALL SONGS" > "$out"; echo "$out"; exit 0; }

if [[ -f "$out" ]]; then
  i_m="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
  o_m="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$o_m" -ge "$i_m" ]]; then
    echo "pick-mood: cache hit at $out ($(cat "$out"))" >&2
    echo "$out"; exit 0
  fi
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

prompt="$tmp/prompt.txt"
python3 "$here/build_prompt.py" "$transcript" "$songs_root" > "$prompt"

reply="$tmp/reply.txt"
if ! run_claude_step pick-mood "$prompt" "$reply" 2>"$tmp/claude.err"; then
  echo "pick-mood: claude step failed; falling back to ALL SONGS" >&2
  cat "$tmp/claude.err" >&2
  : > "$reply"
fi

python3 "$here/parse_reply.py" "$reply" "$songs_root" > "$out"
echo "pick-mood: chose '$(cat "$out")'" >&2
echo "$out"
