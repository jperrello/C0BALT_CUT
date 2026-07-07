#!/usr/bin/env bash
# Offline proof of the fixer loop's git discipline in a throwaway repo:
#   A) a REJECTED fix (gate 2 grade regression) rolls back ONLY the fixer's
#      files — the operator's pre-existing WIP (tracked mod + untracked file) is
#      left intact, and the fixer's newly-created untracked file is cleaned.
#   B) an ACCEPTED fix (gates pass) is KEPT locally (FSF_COMMIT=0 => no commit).
#   C) FSF_RERENDER_CMD unset -> surface-only, the tree is never mutated.
# Canned reviewer via FSF_REPLY_FILE => no shot-scraper / no live model needed.
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
skill="$here/first-span-feedback.sh"
fails=0

ok() { printf 'ok   %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fails=$((fails + 1)); }
eq() { [[ "$2" == "$3" ]] && ok "$1" || { bad "$1"; printf '  got:  %s\n  want: %s\n' "$2" "$3"; }; }

action_of() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["action"])' "$1" 2>/dev/null; }

build_repo() {
  local repo; repo="$(mktemp -d)"
  git -C "$repo" init -q
  git -C "$repo" config user.email t@t.t
  git -C "$repo" config user.name t
  printf 'A' > "$repo/a.txt"                       # fixer will edit this tracked file
  printf 'orig' > "$repo/wip.txt"                  # operator WIP (tracked)
  printf 'work/\noutput/\n' > "$repo/.gitignore"
  git -C "$repo" add -A >/dev/null 2>&1
  git -C "$repo" commit -qm init
  # pre-existing WIP: a tracked modification + an untracked file
  printf 'WIP' > "$repo/wip.txt"
  printf 'U' > "$repo/wip_untracked.txt"
  # span-0 artifacts (under gitignored work/)
  mkdir -p "$repo/work/testsrc"
  printf 'dummy' > "$repo/work/testsrc/span0.mp4"
  printf '{"clip":"x","grade":70,"tier":"FIXABLE","hard_caps":["face_withheld"],"signals":{"frame1_is_face":false},"source":"testsrc"}' \
    > "$repo/work/testsrc/span0.grade.json"
  printf '{"defect":true,"defect_class":"cold_open","signal":"frame1_is_face","where":"fill-vertical","rationale":"frame 1 is not the speaker"}' \
    > "$repo/defect.json"
  echo "$repo"
}

run_loop() {
  local repo="$1" rerender="$2"
  (
    unset FSF_RERENDER_CMD
    export FSF_GIT_ROOT="$repo" FIRST_SPAN_FEEDBACK=1 FSF_REPLY_FILE="$repo/defect.json"
    export FSF_COMMIT=0   # this test proves rollback discipline, not the commit path
    export FSF_FIX_CMD='printf FIXED > a.txt; printf NEW > b_new.txt'
    [[ -n "$rerender" ]] && export FSF_RERENDER_CMD="$rerender"
    bash "$skill" testsrc span0 testslug "$repo/work/testsrc/span0.mp4" >/dev/null 2>&1
  )
  echo $?
}

# ---- Scenario A: reject (gate 2 grade regression) -> rollback ---------------
repoA="$(build_repo)"
printf '{"clip":"x","grade":40,"tier":"DROSS","hard_caps":["face_withheld"],"signals":{"frame1_is_face":false},"source":"testsrc"}' \
  > "$repoA/regressed.grade.json"
rcA="$(run_loop "$repoA" 'cp regressed.grade.json work/testsrc/span0.grade.json')"
eq "A exit 0" "$rcA" "0"
eq "A fixer file reverted" "$(cat "$repoA/a.txt")" "A"
[[ ! -e "$repoA/b_new.txt" ]] && ok "A fixer untracked cleaned" || bad "A fixer untracked cleaned"
eq "A WIP tracked intact" "$(cat "$repoA/wip.txt")" "WIP"
[[ -e "$repoA/wip_untracked.txt" ]] && ok "A WIP untracked intact" || bad "A WIP untracked intact"
eq "A verdict action" "$(action_of "$repoA/work/testsrc/_preview/span0-feedback.json")" "fix_rejected"

# ---- Scenario B: accept (gates pass) -> kept locally, no commit -------------
repoB="$(build_repo)"
printf '{"clip":"x","grade":85,"tier":"GOLD","hard_caps":[],"signals":{"frame1_is_face":true},"source":"testsrc"}' \
  > "$repoB/better.grade.json"
headB0="$(git -C "$repoB" rev-parse HEAD)"
rcB="$(run_loop "$repoB" 'cp better.grade.json work/testsrc/span0.grade.json')"
eq "B exit 0" "$rcB" "0"
eq "B fixer file kept" "$(cat "$repoB/a.txt")" "FIXED"
[[ -e "$repoB/b_new.txt" ]] && ok "B fixer untracked kept" || bad "B fixer untracked kept"
eq "B WIP tracked intact" "$(cat "$repoB/wip.txt")" "WIP"
eq "B no commit made (phase 2)" "$(git -C "$repoB" rev-parse HEAD)" "$headB0"
eq "B verdict action" "$(action_of "$repoB/work/testsrc/_preview/span0-feedback.json")" "fixed_kept_local"

# ---- Scenario C: FSF_RERENDER_CMD unset -> surface only, no mutation --------
repoC="$(build_repo)"
rcC="$(run_loop "$repoC" '')"
eq "C exit 0" "$rcC" "0"
eq "C tree untouched (fixer never ran)" "$(cat "$repoC/a.txt")" "A"
[[ ! -e "$repoC/b_new.txt" ]] && ok "C no fixer artifact" || bad "C no fixer artifact"
eq "C WIP tracked intact" "$(cat "$repoC/wip.txt")" "WIP"
eq "C verdict action" "$(action_of "$repoC/work/testsrc/_preview/span0-feedback.json")" "surface_only_no_rerender"

rm -rf "$repoA" "$repoB" "$repoC"
if [[ "$fails" -gt 0 ]]; then
  printf '\n%d rollback test(s) FAILED\n' "$fails"; exit 1
fi
printf '\nall rollback tests passed\n'
