#!/usr/bin/env bash
# segment-topics: transcript -> contiguous topical chapters (Claude-driven)
set -euo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

transcript="${1:-}"
out="${2:-}"

if [[ -z "$transcript" ]]; then
  echo "usage: segment-topics.sh <transcript.json> [out.json]" >&2
  exit 2
fi
if [[ ! -f "$transcript" ]]; then
  echo "segment-topics: transcript not found: $transcript" >&2
  exit 2
fi

here="$(cd "$(dirname "$0")" && pwd)"
[[ -z "$out" ]] && out="$(dirname "$transcript")/topics.json"

if [[ -f "$out" ]]; then
  in_mtime="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
  out_mtime="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$out_mtime" -ge "$in_mtime" ]]; then
    echo "segment-topics: cache hit at $out" >&2
    echo "$out"
    exit 0
  fi
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# --- rlm-assisted path -----------------------------------------------------
# On long sources the single-prompt compression loses back-half detail. When
# RLM_TOPICS=1, or auto above RLM_TOPICS_MIN_SEC (default 1500s / 25min), fan
# out one rlm-subcall per ~RLM_TOPICS_CHUNK_SEC (default 600s) window and
# synthesize. Falls back to the deterministic single-prompt path on any
# failure. Also emits candidates.hint.json (a pick-segments discovery hint).
duration="$(python3 -c 'import json,sys
tx=json.load(open(sys.argv[1])); s=tx.get("segments") or []
print(int(s[-1]["t1"]) if s else 0)' "$transcript" 2>/dev/null || echo 0)"
rlm_min="${RLM_TOPICS_MIN_SEC:-1500}"
use_rlm=0
if [[ "${RLM_TOPICS:-}" == "1" ]]; then
  use_rlm=1
elif [[ "${RLM_TOPICS:-}" != "0" && "$duration" -ge "$rlm_min" ]]; then
  use_rlm=1
fi

reply="$tmp/reply.txt"
if [[ "$use_rlm" == "1" ]]; then
  echo "segment-topics: rlm-assisted (duration ${duration}s, chunk ${RLM_TOPICS_CHUNK_SEC:-600}s)" >&2
  python3 "$here/build_rlm_prompt.py" "$transcript" "$tmp/chunks" "${RLM_TOPICS_CHUNK_SEC:-600}" > "$tmp/prompt.txt"
  if run_claude_step segment-topics-rlm "$tmp/prompt.txt" "$reply" 2>"$tmp/claude.err" \
     && python3 "$here/parse_reply.py" "$reply" "$transcript" > "$out" 2>"$tmp/parse.err"; then
    hint="$(dirname "$out")/candidates.hint.json"
    python3 "$here/parse_candidates.py" "$reply" "$transcript" > "$hint" 2>/dev/null \
      && echo "segment-topics: wrote candidate hints -> $hint" >&2 || true
    echo "segment-topics: wrote $out (rlm)" >&2
    echo "$out"; exit 0
  fi
  echo "segment-topics: rlm path failed; falling back to single-prompt compression" >&2
  cat "$tmp/claude.err" "$tmp/parse.err" 2>/dev/null >&2 || true
fi

# --- deterministic single-prompt fallback / default -----------------------
python3 "$here/build_prompt.py" "$transcript" > "$tmp/prompt.txt"
run_claude_step segment-topics "$tmp/prompt.txt" "$reply" 2>"$tmp/claude.err" || {
  echo "segment-topics: claude step failed" >&2
  cat "$tmp/claude.err" >&2
  exit 1
}

python3 "$here/parse_reply.py" "$reply" "$transcript" > "$out"
echo "segment-topics: wrote $out" >&2
echo "$out"
