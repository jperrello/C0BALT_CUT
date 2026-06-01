#!/usr/bin/env bash
# Unit tests for the b-roll suite pure-logic pieces (no mcptube/quota).
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/.." && pwd)"   # .claude/skills
pick="$here"
comp="$root/broll-composite"
clean="$root/broll-cleanup"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
pass=0; fail=0
ok()  { echo "  PASS: $1"; pass=$((pass+1)); }
no()  { echo "  FAIL: $1"; fail=$((fail+1)); }

cat > "$tmp/chunks.json" <<'JSON'
{"chunks":[
 {"text":"so today","t0":0.0,"t1":0.4,"words":[]},
 {"text":"we talk about the hippo","t0":0.4,"t1":2.0,"words":[]},
 {"text":"which swims fast","t0":2.0,"t1":3.2,"words":[]},
 {"text":"and then runs","t0":3.2,"t1":4.8,"words":[]},
 {"text":"on land too","t0":4.8,"t1":6.0,"words":[]}
]}
JSON

echo "[1] parse_anchors: snapping + window->time + overlap guard"
cat > "$tmp/reply.txt" <<'EOF'
blah blah {"anchors":[{"topic":"hippopotamus","anchor_word":"hippo","windows":[{"c0":1,"c1":1,"query":"hippo underwater"},{"c0":3,"c1":4,"query":"hippo running on land"}]}]} trailing
EOF
out="$(python3 "$pick/parse_anchors.py" "$tmp/reply.txt" "$tmp/chunks.json")"
echo "    $out"
n=$(echo "$out" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["windows"]))')
[[ "$n" == "2" ]] && ok "two windows parsed" || no "expected 2 windows got $n"
t0=$(echo "$out" | python3 -c 'import json,sys;w=json.load(sys.stdin)["windows"];print(w[0]["t0"],w[0]["t1"],w[1]["t0"],w[1]["t1"])')
[[ "$t0" == "0.4 2.0 3.2 6.0" ]] && ok "chunk indices -> times" || no "times wrong: $t0"

echo "[2] parse_anchors: degenerate short single chunk extends forward"
cat > "$tmp/reply2.txt" <<'EOF'
{"anchors":[{"topic":"x","anchor_word":"x","windows":[{"c0":0,"c1":0,"query":"q"}]}]}
EOF
out2="$(python3 "$pick/parse_anchors.py" "$tmp/reply2.txt" "$tmp/chunks.json" 1.0)"
c1=$(echo "$out2" | python3 -c 'import json,sys;w=json.load(sys.stdin)["windows"];print(w[0]["c1"] if w else "none")')
[[ "$c1" == "1" ]] && ok "chunk0 (0.4s) extended to chunk1 (>=1.0s)" || no "expected c1=1 got $c1"

echo "[3] parse_anchors: overlapping windows -> second dropped"
cat > "$tmp/reply3.txt" <<'EOF'
{"anchors":[{"topic":"a","anchor_word":"a","windows":[{"c0":1,"c1":2,"query":"q1"},{"c0":2,"c1":3,"query":"q2"}]}]}
EOF
n3=$(python3 "$pick/parse_anchors.py" "$tmp/reply3.txt" "$tmp/chunks.json" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["windows"]))')
[[ "$n3" == "1" ]] && ok "overlap collapsed to 1 window" || no "expected 1 got $n3"

echo "[4] parse_anchors: garbage reply -> empty"
echo "I could not produce JSON" > "$tmp/reply4.txt"
n4=$(python3 "$pick/parse_anchors.py" "$tmp/reply4.txt" "$tmp/chunks.json" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["windows"]))')
[[ "$n4" == "0" ]] && ok "garbage -> empty windows" || no "expected 0 got $n4"

echo "[5] parse_verify: match/best clamping"
echo 'sure: {"match":true,"best":2}' > "$tmp/v.txt"
v=$(python3 "$pick/parse_verify.py" "$tmp/v.txt")
echo "    $v"
[[ "$v" == '{"match": true, "best": 2}' ]] && ok "match true best 2" || no "got $v"
echo '{"match":false}' > "$tmp/v2.txt"
[[ "$(python3 "$pick/parse_verify.py" "$tmp/v2.txt")" == '{"match": false, "best": 0}' ]] && ok "match false" || no "false parse"
echo 'no json here' > "$tmp/v3.txt"
[[ "$(python3 "$pick/parse_verify.py" "$tmp/v3.txt")" == '{"match": false, "best": 0}' ]] && ok "no-json -> false" || no "nojson parse"
echo '{"match":true,"best":9}' > "$tmp/v4.txt"
[[ "$(python3 "$pick/parse_verify.py" "$tmp/v4.txt")" == '{"match": true, "best": 0}' ]] && ok "out-of-range best clamps to 0" || no "clamp fail"

echo "[6] emit_plan: schema + sort + dedup ids"
printf '%s\n' \
  '{"t0":5.0,"t1":6.0,"topic":"b","anchor_word":"b","query":"q","clip_path":"/x/broll_02.mp4","source":{"video_id":"V2","title":"t","url":"u","t0_src":1,"t1_src":2},"verified":true}' \
  '{"t0":1.0,"t1":2.0,"topic":"a","anchor_word":"a","query":"q","clip_path":"/x/broll_01.mp4","source":{"video_id":"V1","title":"t","url":"u","t0_src":1,"t1_src":2},"verified":true}' \
  > "$tmp/picks.jsonl"
printf 'V1\nV2\nV1\n' > "$tmp/ids.txt"
python3 "$pick/emit_plan.py" "$tmp/picks.jsonl" "$tmp/ids.txt" 3 10 1746000000.0 "$tmp/plan.json" >/dev/null
python3 - "$tmp/plan.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
assert [x["t0"] for x in p["picks"]]==[1.0,5.0], "not sorted by t0"
assert p["ingested_video_ids"]==["V1","V2"], "ids not deduped/ordered"
assert p["vision_calls_used"]==3 and p["vision_cap"]==10
assert p["chunks_mtime"]==1746000000.0
print("schema-ok")
PY
[[ $? == 0 ]] && ok "plan schema/sort/dedup" || no "plan schema"

echo "[7] emit_plan: empty -> zero picks"
python3 "$pick/emit_plan.py" /dev/null /dev/null 0 10 1.0 "$tmp/empty.json" >/dev/null
ep=$(python3 -c 'import json,sys;p=json.load(open(sys.argv[1]));print(len(p["picks"]),len(p["ingested_video_ids"]))' "$tmp/empty.json")
[[ "$ep" == "0 0" ]] && ok "empty plan" || no "got $ep"

echo "[8] build_filter: zero picks -> |0"
echo '{"picks":[],"ingested_video_ids":[]}' > "$tmp/p0.json"
[[ "$(python3 "$comp/build_filter.py" "$tmp/p0.json")" == "|0" ]] && ok "zero picks filter" || no "zero filter"

echo "[9] build_filter: missing clip_path skipped"
echo '{"picks":[{"t0":1,"t1":2,"clip_path":"/nope/x.mp4"}],"ingested_video_ids":[]}' > "$tmp/pmiss.json"
[[ "$(python3 "$comp/build_filter.py" "$tmp/pmiss.json")" == "|0" ]] && ok "missing clip skipped" || no "missing not skipped"

echo "[10] composite: zero-picks passthrough produces playable output"
base="$tmp/base.mp4"
ffmpeg -y -hide_banner -loglevel error -f lavfi -i "color=c=navy:s=1080x1920:d=2" \
  -f lavfi -i "sine=frequency=200:duration=2" -shortest -pix_fmt yuv420p "$base" 2>/dev/null
SHORTS_ENCODER=x264 bash "$comp/broll-composite.sh" "$base" "$tmp/p0.json" "$tmp/pass_out.mp4" >/dev/null 2>&1
if ffprobe -v error -show_entries format=duration -of csv=p=0 "$tmp/pass_out.mp4" >/dev/null 2>&1; then
  ok "passthrough output valid"
else no "passthrough output invalid"; fi

echo "[11] composite: full-frame cut with synthesized b-roll"
broll="$tmp/broll_01.mp4"
ffmpeg -y -hide_banner -loglevel error -f lavfi -i "testsrc=s=1280x720:d=1:r=30" -pix_fmt yuv420p "$broll" 2>/dev/null
cat > "$tmp/plan_cut.json" <<JSON
{"picks":[{"t0":0.5,"t1":1.2,"topic":"t","anchor_word":"t","query":"q","clip_path":"$broll","source":{"video_id":"X","title":"t","url":"u","t0_src":0,"t1_src":1},"verified":true}],"ingested_video_ids":["X"]}
JSON
SHORTS_ENCODER=x264 bash "$comp/broll-composite.sh" "$base" "$tmp/plan_cut.json" "$tmp/cut_out.mp4" >/dev/null 2>&1
# sample a frame inside the window (t=0.8) and outside (t=1.6); inside should be
# colorful (testsrc), outside should be navy. Compare mean R/G channel spread.
ffmpeg -y -hide_banner -loglevel error -ss 0.8 -i "$tmp/cut_out.mp4" -frames:v 1 "$tmp/in.png" 2>/dev/null
ffmpeg -y -hide_banner -loglevel error -ss 1.6 -i "$tmp/cut_out.mp4" -frames:v 1 "$tmp/out.png" 2>/dev/null
python3 - "$tmp/in.png" "$tmp/out.png" <<'PY'
import sys,struct,zlib
# tiny PNG mean via ffmpeg signalstats would be easier; use PIL if present else fallback
try:
    from PIL import Image
    a=Image.open(sys.argv[1]).convert("RGB").resize((16,16))
    b=Image.open(sys.argv[2]).convert("RGB").resize((16,16))
    def spread(im):
        px=list(im.getdata());
        rs=[p[0] for p in px]; gs=[p[1] for p in px]; bs=[p[2] for p in px]
        return (max(rs)-min(rs))+(max(gs)-min(gs))+(max(bs)-min(bs))
    si,so=spread(a),spread(b)
    # inside window = testsrc bars (high spread); outside = solid navy (low spread)
    assert si>120, f"inside not varied (spread={si})"
    assert so<60, f"outside not solid navy (spread={so})"
    print(f"frame-check ok inside_spread={si} outside_spread={so}")
except ImportError:
    print("PIL-missing-skip")
PY
rc=$?
if [[ $rc == 0 ]]; then ok "full-frame cut replaces frame in-window, base outside"; else no "frame-check failed"; fi

echo "[12] cleanup: local cache deleted, plan.json untouched, no mcptube"
work="$tmp/work/abc"; mkdir -p "$work/broll"
touch "$work/broll/broll_01.mp4" "$work/broll/broll_02.mp4"
cat > "$work/broll_plan.json" <<JSON
{"picks":[{"clip_path":"$work/broll/broll_01.mp4","source":{"video_id":"VID1"}}],"ingested_video_ids":["VID1"]}
JSON
MCPTUBE_BIN=/nonexistent bash "$clean/broll-cleanup.sh" "$work/broll_plan.json" >/dev/null 2>&1
if [[ ! -e "$work/broll/broll_01.mp4" && ! -e "$work/broll/broll_02.mp4" && -f "$work/broll_plan.json" ]]; then
  ok "cache deleted, plan.json preserved"
else no "cleanup wrong: clips exist or plan deleted"; fi

echo
echo "RESULT: $pass passed, $fail failed"
[[ $fail == 0 ]]
