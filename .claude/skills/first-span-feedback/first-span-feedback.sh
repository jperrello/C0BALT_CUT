#!/usr/bin/env bash
# first-span-feedback: the pre-fanout learning gate. start.sh finishes SPAN 0
# alone (through the normal edit/captions/completion chain), then this skill
# records a shot-scraper `video` demo of a generated per-span REVIEW PAGE, has a
# Claude reviewer WATCH it (via a contact sheet, like director-pass), and — when
# the reviewer names a SYSTEMIC defect that clears a hard three-gate re-verify —
# makes a permanent codebase change so every later span (and every future run)
# inherits the fix.
#
# PHASE 2 (this file): record -> review -> (on defect) bounded fix loop with a
# hard THREE-GATE accept:
#   gate 1  re-render span 0 via FSF_RERENDER_CMD (entrypoint-owned)
#   gate 2  check_grade.py: new grade >= prev AND the flagged signal cleared
#   gate 3  re-record + re-review: the defect is gone
# Any gate fail -> roll back ONLY the fixer's edits (git stash snapshot), never
# the operator's pre-existing WIP. All gates pass -> keep the edit locally.
# (Commit + push land in Phase 3; this phase stops at "kept locally".)
#
# If FSF_RERENDER_CMD is unset (or no grade.json), a flagged defect is surfaced
# only — never mutate code we cannot verify.
#
# NON-FATAL everywhere: a missing shot-scraper, a record failure, a parse
# failure, a rejected gate — all leave span 0 and the code untouched and exit 0,
# so fan-out proceeds on unchanged code. Idempotent via a .fsfmeta signature.
#
#   first-span-feedback.sh <work_id> <clip_stem> <slug> <saved_mp4> [--pane <p>]
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }

# git ops + fixer/re-render cwd target the repo; overridable for tests.
git_root="${FSF_GIT_ROOT:-$root}"

frames_py="$here/../director-pass/frames.py"
NFR="${FSF_FRAMES:-12}"
PORT="${FSF_PORT:-8917}"
MAXIT="${FSF_MAX_ITERS:-1}"

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
probe_dur() { ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 "$1" 2>/dev/null; }
gitc() { git -C "$git_root" "$@"; }

# ---- args -----------------------------------------------------------------
id="${1:-}"; stem="${2:-clip_00}"; slug="${3:-}"; saved="${4:-}"
if [[ -z "$id" || -z "$saved" ]]; then
  echo "usage: first-span-feedback.sh <work_id> <clip_stem> <slug> <saved_mp4> [--pane <p>]" >&2
  exit 2
fi

# ---- guard: gated off ------------------------------------------------------
if [[ "${FIRST_SPAN_FEEDBACK:-1}" == "0" ]]; then
  echo "first-span-feedback: disabled (FIRST_SPAN_FEEDBACK=0) — skipping" >&2
  exit 0
fi

dir="$git_root/work/$id"
if [[ ! -f "$saved" ]]; then
  echo "first-span-feedback: saved span-0 clip not found: $saved — skipping" >&2
  exit 0
fi

# grade.json: mirrored next to the saved clip, or the work-dir sidecar.
gradepath() {
  local g
  for g in "${saved%.*}.grade.json" "$dir/$stem.grade.json"; do
    [[ -f "$g" ]] && { echo "$g"; return 0; }
  done
  echo ""
}
grade="$(gradepath)"

# ---- guard: idempotency ----------------------------------------------------
sig="$(mtime "$saved")"
[[ -n "$grade" ]] && sig="$sig|$(mtime "$grade")"
sig="$sig|fsf=${FIRST_SPAN_FEEDBACK:-1}|max=$MAXIT|v2"
meta="$dir/$stem.fsfmeta"
verdict_json="$dir/_preview/span0-feedback.json"
if [[ -f "$verdict_json" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "first-span-feedback: cache hit at $verdict_json" >&2
  exit 0
fi

preview="$dir/_preview"
mkdir -p "$preview"
page="$preview/span0-review.html"
storyboard="$preview/storyboard.yml"
demo="$preview/span0-demo.mp4"
dur="$(probe_dur "$saved")"; [[ -z "$dur" ]] && dur="30"

# canned-reviewer mode (test seam): FSF_REPLY_FILE stands in for the live model,
# so the loop runs fully offline — no shot-scraper, no browser, no live claude.
canned=0
[[ -n "${FSF_REPLY_FILE:-}" ]] && canned=1

# ---- probe: shot-scraper (uvx-isolated, decoupled from the vendored 1.60) --
# Off PATH / not provisionable -> degrade non-fatally: span 0 ships unmodified.
# Skipped in canned mode (nothing to record).
if [[ "$canned" == "0" ]]; then
  if ! command -v uvx >/dev/null 2>&1 || ! uvx shot-scraper --version >/dev/null 2>&1; then
    echo "first-span-feedback: uvx shot-scraper unavailable — skipping demo/review" >&2
    exit 0
  fi
fi

# ---- record_demo -----------------------------------------------------------
# Build the review page + storyboard, serve it over a throwaway http.server, and
# record the page playing span 0 through once. Any failure is non-fatal; review
# then falls back to the raw clip. No-op in canned mode / FSF_SKIP_RECORD=1.
record_demo() {
  [[ "$canned" == "1" || "${FSF_SKIP_RECORD:-0}" == "1" ]] && return 0
  cp -f "$saved" "$preview/span0.mp4" 2>/dev/null || true
  python3 "$here/build_page.py" "${grade:-/dev/null}" "$page" \
    --video span0.mp4 --slug "$slug" --span "${stem##*_}" --dur "$dur" >/dev/null 2>&1 \
    || echo "first-span-feedback: build_page failed — continuing" >&2
  python3 "$here/storyboard.py" "$preview" "$storyboard" \
    --port "$PORT" --dur "$dur" --html span0-review.html --out span0-demo.webm >/dev/null 2>&1 \
    || echo "first-span-feedback: storyboard build failed — continuing" >&2
  if [[ -f "$storyboard" ]]; then
    echo "first-span-feedback: recording demo -> $demo" >&2
    uvx shot-scraper video "$storyboard" -o "$preview/span0-demo.webm" --mp4 --silent >/dev/null 2>&1 \
      || echo "first-span-feedback: shot-scraper record failed — will review the raw clip" >&2
  fi
}

# ---- review ----------------------------------------------------------------
# Watch the recorded demo (or raw clip) via ONE labelled contact sheet and emit
# a verdict reply. phase=initial reads FSF_REPLY_FILE; phase=reverify reads
# FSF_REVERIFY_FILE (falling back to a clean verdict when only FSF_REPLY_FILE is
# set, so a canned-defect initial review does not re-fire on gate 3). Live mode
# routes through pane.sh; any failure -> deterministic clean verdict.
review() {
  local phase="$1" sdir="$2" reply="$3"
  mkdir -p "$sdir"
  if [[ "$phase" == "reverify" ]]; then
    if [[ -n "${FSF_REVERIFY_FILE:-}" && -f "$FSF_REVERIFY_FILE" ]]; then cp "$FSF_REVERIFY_FILE" "$reply"; return 0; fi
    if [[ "$canned" == "1" ]]; then printf '{"defect":false}' > "$reply"; return 0; fi
  else
    if [[ -n "${FSF_REPLY_FILE:-}" && -f "$FSF_REPLY_FILE" ]]; then cp "$FSF_REPLY_FILE" "$reply"; return 0; fi
  fi

  local review_src="$saved"
  [[ -s "$demo" ]] && review_src="$demo"
  local tx=""
  local f
  for f in "$dir/$stem.tight.transcript.json" "$dir/$stem.transcript.json"; do
    [[ -f "$f" ]] && { tx="$f"; break; }
  done

  local sheetjson sheet
  sheetjson="$(python3 "$frames_py" "$review_src" "$sdir" --n "$NFR" 2>/dev/null)"
  sheet="$(printf '%s' "$sheetjson" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("sheet",""))
except Exception: print("")' 2>/dev/null)"
  if [[ -z "$sheet" || ! -f "$sheet" ]]; then
    echo "first-span-feedback: contact sheet build failed ($phase) — surfacing clean verdict" >&2
    printf '{"defect":false}' > "$reply"
    return 0
  fi
  printf '%s' "$sheetjson" > "$sdir/frames.json"
  python3 "$here/build_prompt.py" "$sheet" "$sdir/frames.json" \
    --grade "${grade:-}" --transcript "$tx" --dur "$dur" > "$sdir/prompt.txt" 2>/dev/null \
    || echo "first-span-feedback: prompt build failed ($phase)" >&2
  if [[ ! -f "$sdir/prompt.txt" ]] || ! run_claude_step first-span-review "$sdir/prompt.txt" "$reply" 2>"$sdir/err"; then
    echo "first-span-feedback: reviewer unavailable ($phase) — surfacing clean verdict" >&2
    printf '{"defect":false}' > "$reply"
  fi
}

# ---- verdict helpers -------------------------------------------------------
parse_verdict() { python3 "$here/parse_reply.py" "$1" 2>/dev/null; }
is_defect() {
  printf '%s' "$1" | python3 -c 'import json,sys
try: sys.exit(0 if json.load(sys.stdin).get("defect") else 1)
except Exception: sys.exit(1)'
}
verdict_signal() {
  printf '%s' "$1" | python3 -c 'import json,sys
try: v=json.load(sys.stdin).get("signal") or ""
except Exception: v=""
print(v)'
}

# write span0-feedback.json (the persisted audit verdict).
write_verdict() {
  local action="$1" raw="$2"
  FSF_RAW_VERDICT="$raw" python3 - "$verdict_json" "$saved" "$id" "$stem" "$demo" "$action" <<'PY'
import json, sys, os
out, saved, wid, stem, demo, action = sys.argv[1:7]
try:
    v = json.loads(os.environ.get("FSF_RAW_VERDICT", ""))
except Exception:
    v = {"defect": False}
doc = {
    "work_id": wid, "clip_stem": stem, "clip": saved,
    "demo": demo if os.path.isfile(demo) else "",
    "verdict": v, "action": action, "phase": 2,
}
json.dump(doc, open(out, "w"), indent=2)
sys.stderr.write(json.dumps({"action": action, "defect": bool(v.get("defect"))}) + "\n")
PY
}

# ---- git snapshot + rollback (fixer-scoped) --------------------------------
# snap = a commit object of the full tree (WIP included) WITHOUT touching it.
# fixer_paths = files that differ between snap and the post-fix worktree, plus
# any non-ignored files the fixer newly created. Rollback reverts ONLY those.
tmpd="$(mktemp -d)"
trap 'rm -rf "$tmpd"' EXIT
FSF_SNAP=""

snap_before() {
  FSF_SNAP="$(gitc stash create 2>/dev/null || true)"
  [[ -z "$FSF_SNAP" ]] && FSF_SNAP="$(gitc rev-parse HEAD 2>/dev/null || true)"
  gitc ls-files --others --exclude-standard 2>/dev/null | sort > "$tmpd/untracked.before"
}

fixer_new_untracked() {
  comm -13 "$tmpd/untracked.before" \
    <(gitc ls-files --others --exclude-standard 2>/dev/null | sort)
}

rollback() {
  [[ -z "$FSF_SNAP" ]] && return 0
  # revert tracked files the fixer changed back to the snapshot
  local p
  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    if gitc cat-file -e "$FSF_SNAP:$p" 2>/dev/null; then
      gitc checkout "$FSF_SNAP" -- "$p" 2>/dev/null || true
    else
      gitc rm -f --quiet -- "$p" 2>/dev/null || rm -f "$git_root/$p" 2>/dev/null || true
    fi
  done < <(gitc diff --name-only "$FSF_SNAP" 2>/dev/null)
  # remove files the fixer newly created (never the operator's untracked WIP)
  while IFS= read -r p; do
    [[ -z "$p" ]] && continue
    rm -f "$git_root/$p" 2>/dev/null || true
  done < <(fixer_new_untracked)
}

# ---- fixer -----------------------------------------------------------------
# FSF_FIX_CMD is the injectable seam (default = the agentic claude -p fixer) so
# tests drive a deterministic edit. Runs in the repo root with tool access.
run_fixer() {
  local verdictfile="$1"
  if [[ -n "${FSF_FIX_CMD:-}" ]]; then
    ( cd "$git_root" && eval "$FSF_FIX_CMD" ) >"$tmpd/fix.log" 2>&1 || true
    return 0
  fi
  python3 "$here/fix_prompt.py" "$verdictfile" --grade "${grade:-}" > "$tmpd/fix.prompt" 2>/dev/null \
    || { echo "first-span-feedback: fix_prompt build failed" >&2; return 1; }
  if ! command -v claude >/dev/null 2>&1; then
    echo "first-span-feedback: claude cli unavailable for fixer — skipping fix" >&2
    return 1
  fi
  ( cd "$git_root" && claude -p "$(cat "$tmpd/fix.prompt")" --permission-mode acceptEdits ) \
    >"$tmpd/fix.log" 2>&1 || echo "first-span-feedback: fixer claude -p returned nonzero — continuing" >&2
  return 0
}

# ===========================================================================
# initial record -> review
# ===========================================================================
record_demo
review initial "$preview/review" "$preview/review/reply.txt"
raw_verdict="$(parse_verdict "$preview/review/reply.txt")"
[[ -z "$raw_verdict" ]] && raw_verdict='{"defect": false}'

# ---- clean span 0 ----------------------------------------------------------
if ! is_defect "$raw_verdict"; then
  write_verdict "clean" "$raw_verdict"
  printf '%s' "$sig" > "$meta"
  echo "first-span-feedback: span 0 clean -> $verdict_json" >&2
  exit 0
fi

# ---- guards: cannot verify a code change -> surface only -------------------
if [[ -z "${FSF_RERENDER_CMD:-}" ]]; then
  write_verdict "surface_only_no_rerender" "$raw_verdict"
  printf '%s' "$sig" > "$meta"
  echo "first-span-feedback: defect flagged but FSF_RERENDER_CMD unset — surfaced only -> $verdict_json" >&2
  exit 0
fi
if [[ -z "$grade" || ! -f "$grade" ]]; then
  write_verdict "surface_only_no_grade" "$raw_verdict"
  printf '%s' "$sig" > "$meta"
  echo "first-span-feedback: defect flagged but no grade.json to gate on — surfaced only -> $verdict_json" >&2
  exit 0
fi

# ===========================================================================
# bounded fix loop with the hard three-gate accept
# ===========================================================================
cp -f "$grade" "$tmpd/prev.grade.json"
signal="$(verdict_signal "$raw_verdict")"
printf '%s' "$raw_verdict" > "$tmpd/verdict.json"

accepted=0
final_verdict="$raw_verdict"
for ((it=1; it<=MAXIT; it++)); do
  echo "first-span-feedback: fix attempt $it/$MAXIT (defect signal=${signal:-none})" >&2
  snap_before
  run_fixer "$tmpd/verdict.json"

  # nothing changed -> no fix to verify
  if [[ -z "$(gitc diff --name-only "$FSF_SNAP" 2>/dev/null)" && -z "$(fixer_new_untracked)" ]]; then
    echo "first-span-feedback: fixer made no code change — stop" >&2
    break
  fi

  # ---- gate 1: re-render span 0 on the corrected code ----------------------
  if ! ( cd "$git_root" && eval "$FSF_RERENDER_CMD" ) >&2; then
    echo "first-span-feedback: gate 1 FAIL (re-render errored) — rollback" >&2
    rollback; continue
  fi
  newgrade="$(gradepath)"
  if [[ -z "$newgrade" || ! -f "$newgrade" ]]; then
    echo "first-span-feedback: gate 1 FAIL (no new grade.json) — rollback" >&2
    rollback; continue
  fi

  # ---- gate 2: grade did not regress AND flagged signal cleared ------------
  if ! python3 "$here/check_grade.py" "$tmpd/prev.grade.json" "$newgrade" "$signal" >&2; then
    echo "first-span-feedback: gate 2 FAIL (grade regressed or signal not cleared) — rollback" >&2
    rollback; continue
  fi
  grade="$newgrade"

  # ---- gate 3: re-record + re-review, defect must be gone ------------------
  record_demo
  review reverify "$preview/reverify_$it" "$preview/reverify_$it/reply.txt"
  reverdict="$(parse_verdict "$preview/reverify_$it/reply.txt")"
  [[ -z "$reverdict" ]] && reverdict='{"defect": false}'
  if is_defect "$reverdict"; then
    echo "first-span-feedback: gate 3 FAIL (defect still present) — rollback" >&2
    rollback; continue
  fi

  accepted=1
  final_verdict="$raw_verdict"
  echo "first-span-feedback: all three gates PASSED — fix kept locally (commit deferred to phase 3)" >&2
  break
done

if [[ "$accepted" == "1" ]]; then
  write_verdict "fixed_kept_local" "$final_verdict"
else
  # ensure the tree is clean of any rejected fixer edit
  rollback
  write_verdict "fix_rejected" "$raw_verdict"
fi
printf '%s' "$sig" > "$meta"
echo "first-span-feedback: done (accepted=$accepted) -> $verdict_json" >&2
exit 0
