#!/usr/bin/env bash
# Shared helper for the 8 Claude-driven skills.
#
# Lets each skill drive an existing tmux pane via send-keys + sentinel files
# instead of spawning its own `claude -p` subprocess. Use by sourcing this
# file and calling `run_claude_step` instead of `claude -p`.
#
# Two modes:
#   - SHORTS_PANE unset/empty: behave exactly as before (`claude -p`).
#   - SHORTS_PANE=<tmux_target>: write prompt to
#       $SHORTS_PANE_DIR/<step>/in.txt, send a shell command into the pane
#       that runs `claude -p`, and wait on out.done before reading out.txt.
#
# Read protocol (revised after the original sentinel approach raced — see
# bd shorts-tnd):
#   pane writes out.txt; orchestrator polls it on a tick. A round is
#   "settled" when out.txt is non-empty and its size is unchanged across
#   two consecutive polls. The orchestrator never reads the instant a
#   sentinel appears, so any half-written or stale state naturally falls
#   out across the polling interval — the same pattern the overseer uses
#   when checking crew work.

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

# usage: run_claude_step <step_name> <prompt_file> <reply_file>
# In headless mode, runs claude -p directly.
# In pane mode, drives the pane via tmux and waits on a sentinel.
run_claude_step() {
  local step="$1" prompt="$2" reply="$3"
  if [[ -z "${SHORTS_PANE:-}" ]]; then
    claude -p --output-format text < "$prompt" > "$reply"
    return $?
  fi

  local base="${SHORTS_PANE_DIR:-/tmp/shorts_pane}/${SHORTS_PANE}"
  local dir="$base/$step"
  mkdir -p "$dir"
  rm -f "$dir/out.txt" "$dir/out.done"
  cp "$prompt" "$dir/in.txt"

  # The pane runs a fresh `claude -p` per round. This is cheaper than
  # maintaining a long-lived REPL via send-keys (which is fragile) and
  # naturally gives a clean context per step.
  # unset CLAUDECODE/CLAUDE_CODE_ENTRYPOINT — `claude -p` refuses to nest
  # inside another Claude Code session and this orchestrator is itself
  # commonly invoked from one.
  local cmd="unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT; cat '$dir/in.txt' | claude -p --output-format text > '$dir/out.txt' 2>>'$dir/log'"
  tmux send-keys -t "$SHORTS_PANE" "$cmd" Enter

  # Tick-based settle: out.txt is considered ready when it is non-empty
  # AND its size has not changed across one tick. The sentinel approach
  # (touch out.done at end) raced; this approach naturally waits for
  # whatever the pane finishes writing.
  local tick="${PANE_TICK:-6}"
  local timeout="${PANE_TIMEOUT:-1800}"
  local waited=0 prev=-1 cur=0
  while true; do
    sleep "$tick"
    waited=$((waited + tick))
    cur=$(wc -c < "$dir/out.txt" 2>/dev/null | tr -d ' ')
    [[ -z "$cur" ]] && cur=0
    if (( cur > 0 && cur == prev )); then
      break
    fi
    prev=$cur
    if (( waited >= timeout )); then
      echo "pane.sh: timeout (${timeout}s) waiting on $SHORTS_PANE/$step (last size=$cur)" >&2
      return 1
    fi
  done

  cp "$dir/out.txt" "$reply"
}

# usage: pane_clear
# Issues `/clear` to the pane between unrelated Claude jobs. No-op outside
# pane mode. (We use a fresh `claude -p` per round so there's no persistent
# context to clear anyway — this is mostly a hint for clarity in pane logs.)
pane_clear() {
  [[ -z "${SHORTS_PANE:-}" ]] && return 0
  tmux send-keys -t "$SHORTS_PANE" "echo '--- clear ---'" Enter
}
