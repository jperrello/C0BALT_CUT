#!/usr/bin/env bash
# Shared timing instrument. Source this file then bracket each skill call with
# `timed <label> <kind> -- <cmd...>`; every call appends one JSONL record to
# $SHORTS_TIMING_LOG. The reducer (timing-report.py) folds the log into a
# machine report (work/<id>/run_timing.json) + a human report
# (output/<slug>/_timing.html) in the end-of-run tail.
#
# Two seams every step already passes through:
#   - start.sh wraps each skill invocation with `timed` (skill granularity,
#     knows lane/span/phase via exported SHORTS_TL_* context).
#   - pane.sh::run_claude_step appends a kind:"claude" sub-record for the
#     measured model+poll time of one Claude round-trip.
#
# Disabled by default: with SHORTS_TIMING_LOG unset, `_timing_emit` is a no-op
# and `timed` is a transparent passthrough (preserves exit code / stdout /
# stderr). The log is append-only; a single `printf >>` is atomic under
# O_APPEND so concurrent lanes never corrupt each other's writes.
#
# bash 3.2: no $EPOCHREALTIME, so _now shells python3 time.monotonic.

# Guard against double-source (start.sh + a sourced pane.sh both pull this in).
[[ -n "${_SHORTS_TIMING_SH:-}" ]] && return 0
_SHORTS_TIMING_SH=1

# Monotonic seconds as a float. monotonic so a wall-clock adjustment mid-run
# never yields a negative duration.
_now() {
  python3 -c 'import time; print(time.monotonic())'
}

# _timing_emit <label> <kind> <t0> <t1> <rc>
# Append one JSONL record. No-op when SHORTS_TIMING_LOG is unset/empty.
# lane/span/phase come from the exported context vars (default to null).
_timing_emit() {
  [[ -z "${SHORTS_TIMING_LOG:-}" ]] && return 0
  local label="$1" kind="$2" t0="$3" t1="$4" rc="$5"
  # python emits a single well-formed line: it JSON-quotes the strings and
  # renders an unset lane/span as the JSON literal null. The append is one
  # write() so it lands atomically under O_APPEND across lanes.
  python3 -c '
import json, os, sys
label, kind, t0, t1, rc = sys.argv[1:6]
def numornull(v):
    v = (v or "").strip()
    return v if v else "null"
rec = {
    "label": label,
    "kind": kind,
    "lane": None if not os.environ.get("SHORTS_TL_LANE") else int(os.environ["SHORTS_TL_LANE"]),
    "span": None if not os.environ.get("SHORTS_TL_SPAN") else int(os.environ["SHORTS_TL_SPAN"]),
    "phase": os.environ.get("SHORTS_TL_PHASE") or None,
    "t0": float(t0),
    "t1": float(t1),
    "exit": int(rc),
}
with open(os.environ["SHORTS_TIMING_LOG"], "a") as f:
    f.write(json.dumps(rec) + "\n")
' "$label" "$kind" "$t0" "$t1" "$rc" 2>/dev/null || true
  return 0
}

# timed <label> <kind> -- <cmd...>
# Bracket a command with the monotonic clock; preserve its exit code, stdout,
# and stderr; append one record. Fully transparent — never aborts the run.
timed() {
  local label="$1" kind="$2"
  shift 2
  [[ "${1:-}" == "--" ]] && shift
  local t0 rc
  t0="$(_now)"
  "$@"
  rc=$?
  _timing_emit "$label" "$kind" "$t0" "$(_now)" "$rc"
  return $rc
}
