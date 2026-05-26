#!/usr/bin/env bash
# broll-pick: Claude-driven Pexels candidate selection with vision verification.
# Emits broll_plan.json — a list of {t0,t1,query,clip_path,anchor_word}.
# No video output. Pair with broll-composite to render.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

input="${1:-}"
transcript="${2:-}"
plan_out="${3:-}"
ingest="${4:-}"
chunks="${5:-}"

if [[ -z "$input" || -z "$transcript" || -z "$plan_out" ]]; then
  echo "usage: broll-pick.sh <input> <transcript.json> <broll_plan.json> [ingest.json] [chunks.json]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "broll-pick: input not found: $input" >&2; exit 2; }
[[ -f "$transcript" ]] || { echo "broll-pick: transcript not found: $transcript" >&2; exit 2; }
[[ -z "$ingest" || -f "$ingest" ]] || { echo "broll-pick: ingest not found: $ingest" >&2; exit 2; }
[[ -z "$chunks" || -f "$chunks" ]] || { echo "broll-pick: chunks not found: $chunks" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
env_file="$root/.env"

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
in_m="$(mtime "$input")"
tx_m="$(mtime "$transcript")"
ch_m="$( [[ -n "$chunks" ]] && mtime "$chunks" || echo 0 )"

meta="$plan_out.pickmeta"
sig="$in_m|$tx_m|$ch_m|v1"
if [[ -f "$plan_out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "broll-pick: cache hit at $plan_out" >&2
  echo "$plan_out"; exit 0
fi

dur="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$input")"
[[ -n "$dur" ]] || { echo "broll-pick: could not read duration" >&2; exit 1; }

# Output directory for downloaded Pexels clips. Co-locate with plan_out.
outdir="$(dirname "$plan_out")/broll_$(basename "$plan_out" .json)"
mkdir -p "$outdir"

emit_empty() {
  printf '%s' '{"picks": []}' > "$plan_out"
  printf '%s' "$sig" > "$meta"
  echo "broll-pick: $1 — empty plan at $plan_out" >&2
  echo "$plan_out"; exit 0
}

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Step 1: Claude picks anchor slots
prompt="$tmp/prompt.txt"
python3 "$here/build_prompt.py" "$transcript" "$dur" "$ingest" > "$prompt"

reply="$tmp/reply.txt"
if ! run_claude_step broll-pick "$prompt" "$reply" 2>"$tmp/claude.err"; then
  echo "broll-pick: claude step (anchor pick) failed" >&2
  cat "$tmp/claude.err" >&2
  : > "$reply"
fi

picks="$tmp/picks.json"
python3 "$here/parse_reply.py" "$reply" "$dur" > "$picks"
npicks="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["picks"]))' "$picks")"
echo "broll-pick: claude picked $npicks raw anchor slot(s)" >&2
[[ "$npicks" -gt 0 ]] || emit_empty "no picks"

# Step 2: orchestrate Pexels + vision verify + (optional) rewrite + plan.json
python3 "$here/plan.py" "$picks" "$input" "$outdir" "$env_file" "${chunks:-}" "$plan_out"
[[ -f "$plan_out" ]] || emit_empty "plan.py emitted nothing"

printf '%s' "$sig" > "$meta"
echo "$plan_out"
