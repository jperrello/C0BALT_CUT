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
# Sentinel protocol (matches May26-spec §1):
#   pane writes out.txt fully, syncs, then touches out.done.
#   orchestrator (us) only reads out.txt after seeing out.done.

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
  rm -f "$dir/out.done" "$dir/out.txt"
  cp "$prompt" "$dir/in.txt"

  # The pane runs a fresh `claude -p` per round. This is cheaper than
  # maintaining a long-lived REPL via send-keys (which is fragile) and
  # naturally gives a clean context per step.
  # unset CLAUDECODE/CLAUDE_CODE_ENTRYPOINT — `claude -p` refuses to nest
  # inside another Claude Code session and this orchestrator is itself
  # commonly invoked from one.
  local cmd="unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT; cat '$dir/in.txt' | claude -p --output-format text > '$dir/out.txt' 2>>'$dir/log' ; sync ; touch '$dir/out.done'"
  tmux send-keys -t "$SHORTS_PANE" "$cmd" Enter

  local timeout="${PANE_TIMEOUT:-1800}"
  local waited=0
  while [[ ! -f "$dir/out.done" ]]; do
    sleep 2
    waited=$((waited + 2))
    if (( waited >= timeout )); then
      echo "pane.sh: timeout (${timeout}s) waiting on $SHORTS_PANE/$step" >&2
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
