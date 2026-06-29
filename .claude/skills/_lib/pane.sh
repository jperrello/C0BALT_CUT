#!/usr/bin/env bash
# Shared helper for the 8 Claude-driven skills.
#
# Lets each skill drive an existing tmux pane via send-keys + sentinel files.
# Use by sourcing this file and calling `run_claude_step` instead of
# `claude -p`.
#
# Three modes:
#   - SHORTS_PANE unset/empty: behave exactly as before (`claude -p`).
#   - SHORTS_PANE=<tmux_target>: write prompt to
#       $SHORTS_PANE_DIR/<step>/in.txt, send a shell command into the pane
#       that runs `claude -p`, and wait on out.done before reading out.txt.
#   - SHORTS_PANE_MODE=chat: the pane is a long-lived interactive Claude
#       session. Send it a small file-based task: read in.txt, write out.txt,
#       touch out.done. This preserves lane context across related steps.
#
# Read protocol (revised after the original sentinel approach raced — see
# bd shorts-tnd):
#   pane writes out.txt; orchestrator polls it on a tick. A round is
#   "settled" when out.txt is non-empty and its size is unchanged across
#   two consecutive polls. The orchestrator never reads the instant a
#   sentinel appears, so any half-written or stale state naturally falls
#   out across the polling interval — the same pattern the overseer uses
#   when checking crew work.

# Pull in the timing instrument so run_claude_step can append its measured
# `claude` sub-record to the same JSONL the start.sh wrapper writes. No-op
# when SHORTS_TIMING_LOG is unset (timing.sh guards _timing_emit). Guarded so a
# missing file never breaks a skill that only sources pane.sh.
_pane_timing="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/timing.sh"
# shellcheck source=/dev/null
[[ -f "$_pane_timing" ]] && source "$_pane_timing"

# usage: parse_pane_flag "$@" ; set -- "${SHORTS_REST[@]}"
# Strips `--pane <name>` from $@, exports SHORTS_PANE, and returns the
# remaining args via SHORTS_REST.
parse_pane_flag() {
  SHORTS_REST=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --pane)
        export SHORTS_PANE="${2:-}"
        shift 2
        ;;
      --pane=*)
        export SHORTS_PANE="${1#--pane=}"
        shift
        ;;
      *)
        SHORTS_REST+=("$1")
        shift
        ;;
    esac
  done
}

run_claude_step() {
  local step="$1" prompt="$2" reply="$3"
  local _t0; _t0="$(_now 2>/dev/null || echo 0)"
  if [[ -z "${SHORTS_PANE:-}" ]]; then
    local _rc
    claude -p --output-format text < "$prompt" > "$reply"
    _rc=$?
    _timing_emit "${step}/claude" claude "$_t0" "$(_now 2>/dev/null || echo 0)" "$_rc"
    return $_rc
  fi

  local base="${SHORTS_PANE_DIR:-/tmp/shorts_pane}/${SHORTS_PANE}"
  local dir="$base/$step"
  mkdir -p "$dir"
  rm -f "$dir/out.txt" "$dir/out.done"
  cp "$prompt" "$dir/in.txt"

  if [[ "${SHORTS_PANE_MODE:-}" == "chat" ]]; then
    local msg
    msg="$(python3 - "$step" "$dir/in.txt" "$dir/out.txt" "$dir/out.done" <<'PY'
import json, sys
step, prompt, out, done = sys.argv[1:]
print(
    "Shorts pane step "
    + json.dumps(step)
    + ". Read the task prompt from "
    + json.dumps(prompt)
    + ". Save the raw parser reply to "
    + json.dumps(out)
    + " using the Bash tool with a heredoc — do NOT use the Write or Edit tools (they trigger a permission menu that blocks the pane). Shape: `cat > "
    + out
    + " <<'PANE_EOF'\\n<your entire reply here, verbatim, no fences>\\nPANE_EOF`. Then run: "
    + json.dumps(f"touch {done}")
    + ". Do not stop until both files exist."
)
PY
)"
    # Paste the prompt, then pause before Enter: a single Enter fired
    # immediately after a literal send races the TUI's bracketed-paste
    # handler and the message sits unsubmitted in the input box. Sleep,
    # then send Enter twice with a gap to guarantee submission.
    tmux send-keys -t "$SHORTS_PANE" -l -- "$msg"
    sleep 1
    tmux send-keys -t "$SHORTS_PANE" Enter
    sleep 0.5
    tmux send-keys -t "$SHORTS_PANE" Enter
  else
    # unset CLAUDECODE/CLAUDE_CODE_ENTRYPOINT — `claude -p` refuses to nest
    # inside another Claude Code session and this orchestrator is itself
    # commonly invoked from one.
    local cmd="unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT; cat '$dir/in.txt' | claude -p --output-format text > '$dir/out.txt' 2>>'$dir/log'; touch '$dir/out.done'"
    tmux send-keys -t "$SHORTS_PANE" "$cmd" Enter
  fi

  local tick="${PANE_TICK:-2}"
  local timeout="${PANE_TIMEOUT:-1800}"
  local waited=0 prev=-1 cur=0
  while true; do
    sleep "$tick"
    waited=$((waited + tick))
    if [[ -f "$dir/out.txt" ]]; then
      cur=$(wc -c < "$dir/out.txt" | tr -d ' ')
      [[ -z "$cur" ]] && cur=0
    else
      cur=0
    fi
    if (( cur > 0 && cur == prev )); then
      break
    fi
    prev=$cur
    if (( cur == 0 && waited >= tick )) && [[ -f "$dir/out.done" ]]; then
      echo "pane.sh: $SHORTS_PANE/$step produced empty output" >&2
      tmux capture-pane -t "$SHORTS_PANE" -p -S -2000 > "$dir/pane.log" 2>/dev/null || true
      return 1
    fi
    if (( waited >= timeout )); then
      echo "pane.sh: timeout (${timeout}s) waiting on $SHORTS_PANE/$step (last size=$cur)" >&2
      tmux capture-pane -t "$SHORTS_PANE" -p -S -2000 > "$dir/pane.log" 2>/dev/null || true
      return 1
    fi
  done

  cp "$dir/out.txt" "$reply"
  _timing_emit "${step}/claude" claude "$_t0" "$(_now 2>/dev/null || echo 0)" 0
}

# usage: pane_clear
# Issues `/clear` to the pane between unrelated Claude jobs. No-op outside
# pane mode. In chat mode this is how the orchestrator preserves context
# inside one source/span lane without carrying it into unrelated work.
pane_clear() {
  [[ -z "${SHORTS_PANE:-}" ]] && return 0
  if [[ "${SHORTS_PANE_MODE:-}" == "chat" ]]; then
    # paste-pause-Enter, same as run_claude_step: an immediate Enter races
    # the TUI and leaves "/clear" unsubmitted in the input box.
    tmux send-keys -t "$SHORTS_PANE" -l -- "/clear"
    sleep 1
    tmux send-keys -t "$SHORTS_PANE" Enter
    sleep 0.5
    tmux send-keys -t "$SHORTS_PANE" Enter
    return 0
  fi
  tmux send-keys -t "$SHORTS_PANE" "echo '--- clear ---'" Enter
}
