#!/usr/bin/env bash
# style-gate: the online VERIFY half of the style-replication loop — the
# first-span-feedback discipline with a DIFFERENT oracle (external exemplar
# match instead of internal grade>=prev) and a DIFFERENT sensor (a sidecar-free
# watched profile instead of grade.json).
#
# After span 0 is delivered (and first-span-feedback has run), profile it from
# PIXELS ONLY (profile-clip), compare against references/targets.json
# (match.py, z-score on LEVERED fields only), and on a mismatch run a bounded
# knob-first fix loop:
#   moves.py -> work/<id>/style.env (clamped env deltas: JUMP_CUT_SEG,
#   JUMP_CUT_MAX_GAP, SPEED, SWITCH_SPACING)
#   -> SG_RERENDER_CMD (entrypoint-owned span-0 re-render with style.env applied)
#   -> re-profile + re-match
#   accept iff accept.py passes (no checked field worse, >=1 improved, no new
#   mismatch) AND span 0's grade.json did not regress.
# Accept -> style.env persists for spans 1..N (the caller sources it) + the
# outcome is appended to references/accepted.jsonl (the learning ledger).
# Reject -> style.env deleted; knobs and code untouched.
#
# Risk ladder: this gate moves ONLY ephemeral per-run env knobs. Mismatches no
# knob can reach are SURFACED in the verdict for an operator-approved durable
# code change (see SPEC-style-replication.md §5).
#
# Self-arming: no targets.json (or corpus n < SG_MIN_REFS) -> exit 0 untouched,
# so out of the box the pipeline is byte-identical to today. STYLE_GATE=0
# force-disables. NON-FATAL everywhere. Idempotent via .sgmeta.
#
#   style-gate.sh <work_id> <clip_stem> <saved_mp4> [--pane <p>]
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }

id="${1:-}"; stem="${2:-clip_00}"; saved="${3:-}"
if [[ -z "$id" || -z "$saved" ]]; then
  echo "usage: style-gate.sh <work_id> <clip_stem> <saved_mp4> [--pane <p>]" >&2
  exit 2
fi

[[ "${STYLE_GATE:-1}" == "0" ]] && { echo "style-gate: disabled (STYLE_GATE=0)" >&2; exit 0; }
refs="${STYLE_REFS:-$root/references}"
targets="$refs/targets.json"
[[ -f "$targets" ]] || { echo "style-gate: no corpus targets at $targets — skipping" >&2; exit 0; }
[[ -f "$saved" ]] || { echo "style-gate: saved clip not found: $saved — skipping" >&2; exit 0; }

dir="$root/work/$id"
MAXIT="${SG_MAX_ITERS:-1}"
styleenv="$dir/style.env"
verdictout="$dir/$stem.style.json"

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
meta="$dir/$stem.sgmeta"
sig="$(mtime "$saved")|$(mtime "$targets")|z=${SG_Z:-1.5}|it=$MAXIT|v1"
if [[ -f "$verdictout" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "style-gate: cache hit at $verdictout" >&2
  exit 0
fi
rm -f "$styleenv"

grade() {
  local g
  for g in "${saved%.*}.grade.json" "$dir/$stem.grade.json"; do
    [[ -f "$g" ]] && { echo "$g"; return 0; }
  done
  echo ""
}

pflags=()
[[ -n "${SHORTS_PANE:-}" ]] && pflags=(--pane "$SHORTS_PANE")

# SG_PROFILE_FILE / SG_REPROFILE_FILE: canned-profile test seams (like
# FSF_REPLY_FILE) — the gate loop runs fully offline, no ffmpeg/whisper.
sg_profiled=0
run_profile() {
  if [[ "$sg_profiled" == "0" && -n "${SG_PROFILE_FILE:-}" && -f "${SG_PROFILE_FILE:-}" ]]; then
    cp -f "$SG_PROFILE_FILE" "$2"; sg_profiled=1; return 0
  fi
  if [[ "$sg_profiled" != "0" && -n "${SG_REPROFILE_FILE:-}" && -f "${SG_REPROFILE_FILE:-}" ]]; then
    cp -f "$SG_REPROFILE_FILE" "$2"; return 0
  fi
  rm -f "${2%.json}.ppmeta" 2>/dev/null
  PROFILE_VISION=0 bash "$here/../profile-clip/profile-clip.sh" "$1" "$2" ${pflags[@]+"${pflags[@]}"} >&2
}

run_match() {
  python3 "$here/match.py" "$1" "$targets" "$2" >&2
}

finish() {
  printf '%s' "$sig" > "$meta"
  echo "style-gate: done ($1) -> $verdictout" >&2
  exit 0
}

# ---- initial profile + match ------------------------------------------------
profile="$dir/$stem.styleprofile.json"
run_profile "$saved" "$profile" || { echo "style-gate: profile failed — skipping" >&2; exit 0; }
if run_match "$profile" "$verdictout"; then
  finish "match"
fi
[[ -n "${SG_RERENDER_CMD:-}" ]] || { echo "style-gate: mismatch surfaced (SG_RERENDER_CMD unset — no knob loop)" >&2; finish "surfaced"; }

prevgrade="$(grade)"
tmpd="$(mktemp -d)"
trap 'rm -rf "$tmpd"' EXIT
[[ -n "$prevgrade" ]] && cp -f "$prevgrade" "$tmpd/prev.grade.json"

# ---- bounded knob loop -------------------------------------------------------
accepted=0
for ((it=1; it<=MAXIT; it++)); do
  if ! python3 "$here/moves.py" "$verdictout" "$styleenv" >&2; then
    echo "style-gate: no reachable knob move — surfaced" >&2
    rm -f "$styleenv"
    break
  fi
  echo "style-gate: attempt $it/$MAXIT with $(tr '\n' ' ' < "$styleenv")" >&2

  if ! ( set -a; . "$styleenv"; set +a; cd "$root" && eval "$SG_RERENDER_CMD" ) >&2; then
    echo "style-gate: re-render failed — reject" >&2
    rm -f "$styleenv"
    break
  fi
  run_profile "$saved" "$tmpd/new.styleprofile.json" || { rm -f "$styleenv"; break; }
  run_match "$tmpd/new.styleprofile.json" "$tmpd/new.style.json" || true

  if ! python3 "$here/accept.py" "$verdictout" "$tmpd/new.style.json" >&2; then
    echo "style-gate: style did not improve — reject" >&2
    rm -f "$styleenv"
    break
  fi
  newgrade="$(grade)"
  if [[ -f "$tmpd/prev.grade.json" && -n "$newgrade" ]]; then
    if ! python3 "$here/../first-span-feedback/check_grade.py" "$tmpd/prev.grade.json" "$newgrade" "" >&2; then
      echo "style-gate: grade regressed — reject" >&2
      rm -f "$styleenv"
      break
    fi
  fi
  cp -f "$tmpd/new.style.json" "$verdictout"
  cp -f "$tmpd/new.styleprofile.json" "$profile"
  accepted=1
  break
done

if [[ "$accepted" == "1" ]]; then
  python3 - "$refs/accepted.jsonl" "$styleenv" "$verdictout" "$id" <<'PY' 2>/dev/null || true
import json, sys
led, env, verdict, wid = sys.argv[1:5]
moves = dict(l.replace("export ", "").split("=", 1) for l in open(env).read().split("\n") if "=" in l)
v = json.load(open(verdict))
rec = {"work_id": wid, "moves": moves, "match": v.get("match"),
       "mismatches": [m["field"] for m in v.get("mismatches", [])]}
open(led, "a").write(json.dumps(rec) + "\n")
PY
  echo "style-gate: knob move ACCEPTED — spans 1..N inherit $styleenv" >&2
  finish "accepted"
fi

# rejected/surfaced: re-render span 0 back on stock knobs if we mutated it
if [[ ! -f "$styleenv" && "$accepted" == "0" && -n "${SG_RERENDER_CMD:-}" && "${it:-1}" -gt 0 ]]; then
  if [[ -f "$tmpd/new.styleprofile.json" ]]; then
    echo "style-gate: restoring span 0 on stock knobs" >&2
    ( cd "$root" && eval "$SG_RERENDER_CMD" ) >&2 || echo "style-gate: restore render failed (non-fatal)" >&2
  fi
fi
finish "rejected"
