#!/usr/bin/env bash
# Offline proof of the accept-path COMMIT discipline in a throwaway repo:
#   an ACCEPTED fix (all three gates pass) commits ONLY the fixer's exact path
#   set (a tracked edit + a fixer-created file), leaving the operator's
#   pre-existing WIP (tracked mod + untracked file) neither committed nor rolled
#   back, and excluding the re-rendered media under a gitignored dir. push/pull
#   have no remote -> they fail non-fatally and the loop still exits 0.
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
  # pre-existing operator WIP: a tracked modification + an untracked file
  printf 'WIP' > "$repo/wip.txt"
  printf 'U' > "$repo/wip_untracked.txt"
  # span-0 artifacts (under gitignored work/)
  mkdir -p "$repo/work/testsrc"
  printf 'dummy' > "$repo/work/testsrc/span0.mp4"
  printf '{"clip":"x","grade":70,"tier":"FIXABLE","hard_caps":["face_withheld"],"signals":{"frame1_is_face":false},"source":"testsrc"}' \
    > "$repo/work/testsrc/span0.grade.json"
  printf '{"clip":"x","grade":85,"tier":"GOLD","hard_caps":[],"signals":{"frame1_is_face":true},"source":"testsrc"}' \
    > "$repo/better.grade.json"
  printf '{"defect":true,"defect_class":"cold_open","signal":"frame1_is_face","where":"fill-vertical","rationale":"frame 1 is not the speaker"}' \
    > "$repo/defect.json"
  echo "$repo"
}

repo="$(build_repo)"
head0="$(git -C "$repo" rev-parse HEAD)"
(
  unset FSF_COMMIT
  export FSF_GIT_ROOT="$repo" FIRST_SPAN_FEEDBACK=1 FSF_REPLY_FILE="$repo/defect.json"
  # fixer edits a tracked file + creates a new one; re-render writes a BETTER
  # grade.json under the gitignored work/ dir (must NOT be committed).
  export FSF_FIX_CMD='printf FIXED > a.txt; printf NEW > b_new.txt'
  export FSF_RERENDER_CMD='cp better.grade.json work/testsrc/span0.grade.json'
  bash "$skill" testsrc span0 testslug "$repo/work/testsrc/span0.mp4" >/dev/null 2>&1
)
rc=$?

# committed file set (exactly the fixer's paths)
committed="$(git -C "$repo" diff-tree --no-commit-id --name-only -r HEAD 2>/dev/null | sort | tr '\n' ' ')"
committed="${committed% }"

eq "exit 0" "$rc" "0"
[[ "$(git -C "$repo" rev-parse HEAD)" != "$head0" ]] && ok "a commit was made" || bad "a commit was made"
eq "commit contains ONLY the fixer's paths" "$committed" "a.txt b_new.txt"
[[ "$committed" != *"wip.txt"* ]] && ok "operator WIP not committed" || bad "operator WIP not committed"
[[ "$committed" != *"span0.grade.json"* && "$committed" != *"work/"* ]] \
  && ok "gitignored re-rendered media excluded" || bad "gitignored re-rendered media excluded"
# operator WIP survives in the worktree, still uncommitted
eq "WIP tracked mod intact in worktree" "$(cat "$repo/wip.txt")" "WIP"
eq "WIP tracked mod still uncommitted" "$(git -C "$repo" status --porcelain -- wip.txt)" " M wip.txt"
[[ -e "$repo/wip_untracked.txt" ]] && ok "WIP untracked intact" || bad "WIP untracked intact"
eq "WIP untracked still untracked" "$(git -C "$repo" status --porcelain -- wip_untracked.txt)" "?? wip_untracked.txt"
# fixer files landed in the worktree
eq "fixer edit kept" "$(cat "$repo/a.txt")" "FIXED"
# push has no remote -> committed-but-not-pushed
eq "verdict action = committed_local (no remote to push)" \
  "$(action_of "$repo/work/testsrc/_preview/span0-feedback.json")" "fixed_committed_local"

rm -rf "$repo"
if [[ "$fails" -gt 0 ]]; then
  printf '\n%d commit-scope test(s) FAILED\n' "$fails"; exit 1
fi
printf '\nall commit-scope tests passed\n'
