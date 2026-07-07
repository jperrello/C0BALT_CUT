#!/usr/bin/env bash
# Offline tests for the style-gate loop using the SG_PROFILE_FILE /
# SG_REPROFILE_FILE canned seams — no ffmpeg, no whisper, no Claude.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
fails=0
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fails=$((fails+1)); fi; }

td="$(mktemp -d)"
trap 'rm -rf "$td"' EXIT
mkdir -p "$td/refs/profiles" "$td/work/w1"

profile() {
  local out="$1" cpm="$2" med="$3" gap="$4" cut="$5"
  cat > "$out" <<EOF
{"style_profile_version":1,"clip":"x.mp4","duration_sec":40,
 "cuts":{"cuts_per_min":$cpm,"median_shot_sec":$med,"p90_shot_sec":5,"longest_static_gap":$gap},
 "speech":{"max_silence_sec":0.5,"speech_fraction":0.9},
 "visual":{"cutaway_fraction":$cut,"face_fraction":0.5,"cutaway_count":4},
 "captions":{"present_fraction":0.8},"audio":{},"hook":{},"vision":{},"meta":{}}
EOF
}

for i in 0 1 2 3; do
  profile "$td/refs/profiles/r$i.styleprofile.json" "$((34+i))" 1.4 4.$i 0.45
done
python3 "$here/../style-corpus/distill.py" "$td/refs" "$td/refs/targets.json" >/dev/null

saved="$td/work/w1/fake.mp4"; : > "$saved"
common=(env STYLE_REFS="$td/refs" FSF_GIT_ROOT="$root")

# 1. no targets -> no-op exit 0, no verdict
out="$(STYLE_REFS="$td/empty" bash "$here/style-gate.sh" w1 clip_00 "$saved" 2>&1)"; rc=$?
check "no corpus -> skip, exit 0" '[[ $rc -eq 0 && "$out" == *"no corpus"* ]]'

# work dir must be the real repo's work/<id> — use a scratch id under the repo
wid="_sgtest_$$"
mkdir -p "$root/work/$wid"
cleanup_wid() { rm -rf "$root/work/$wid"; }

# 2. matching profile -> match, no style.env
profile "$td/match.json" 35 1.4 4.1 0.45
STYLE_REFS="$td/refs" SG_PROFILE_FILE="$td/match.json" \
  bash "$here/style-gate.sh" "$wid" clip_00 "$saved" >/dev/null 2>&1
check "match -> verdict written" '[[ -f "$root/work/$wid/clip_00.style.json" ]]'
check "match -> match:true" 'python3 -c "import json,sys;sys.exit(0 if json.load(open(\"$root/work/$wid/clip_00.style.json\"))[\"match\"] else 1)"'
check "match -> no style.env" '[[ ! -f "$root/work/$wid/style.env" ]]'
rm -rf "$root/work/$wid"; mkdir -p "$root/work/$wid"

# 3. mismatch, no SG_RERENDER_CMD -> surfaced only
profile "$td/bad.json" 10 4.0 12 0.05
out="$(STYLE_REFS="$td/refs" SG_PROFILE_FILE="$td/bad.json" \
  bash "$here/style-gate.sh" "$wid" clip_00 "$saved" 2>&1)"
check "mismatch surfaced without rerender" '[[ "$out" == *"surfaced"* && ! -f "$root/work/$wid/style.env" ]]'
rm -rf "$root/work/$wid"; mkdir -p "$root/work/$wid"

# 4. mismatch + rerender improves -> accepted, style.env kept, ledger appended
profile "$td/better.json" 30 1.8 5.0 0.35
out="$(STYLE_REFS="$td/refs" SG_PROFILE_FILE="$td/bad.json" SG_REPROFILE_FILE="$td/better.json" \
  SG_RERENDER_CMD="true" bash "$here/style-gate.sh" "$wid" clip_00 "$saved" 2>&1)"
check "improved rerender -> accepted" '[[ "$out" == *"ACCEPTED"* && -f "$root/work/$wid/style.env" ]]'
check "accepted -> ledger row" '[[ -s "$td/refs/accepted.jsonl" ]]'
check "style.env has a knob" 'grep -q "export" "$root/work/$wid/style.env"'
rm -rf "$root/work/$wid"; mkdir -p "$root/work/$wid"

# 5. mismatch + rerender does NOT improve -> rejected, style.env removed
out="$(STYLE_REFS="$td/refs" SG_PROFILE_FILE="$td/bad.json" SG_REPROFILE_FILE="$td/bad.json" \
  SG_RERENDER_CMD="true" bash "$here/style-gate.sh" "$wid" clip_00 "$saved" 2>&1)"
check "no-improve rerender -> rejected" '[[ "$out" == *"rejected"* && ! -f "$root/work/$wid/style.env" ]]'

# 6. STYLE_GATE=0 -> disabled
out="$(STYLE_GATE=0 STYLE_REFS="$td/refs" bash "$here/style-gate.sh" "$wid" clip_00 "$saved" 2>&1)"
check "STYLE_GATE=0 -> disabled" '[[ "$out" == *"disabled"* ]]'
cleanup_wid

echo
if [[ $fails -eq 0 ]]; then echo "ALL PASS"; else echo "$fails FAILURE(S)"; exit 1; fi
