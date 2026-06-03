#!/usr/bin/env bash
# broll-pick: Claude picks visualizable anchors; mcptube/yt-dlp source candidate
# footage; Claude vision-verifies each window; chosen segments download into
# work/<id>/broll/. Emits broll_plan.json. No API key (Claude via host/pane).
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

transcript="${1:-}"
chunks="${2:-}"
ingest="${3:-}"
out="${4:-}"

if [[ -z "$transcript" || -z "$chunks" || -z "$ingest" || -z "$out" ]]; then
  echo "usage: broll-pick.sh <clip_transcript.json> <chunks.json> <ingest.json> <out_broll_plan.json>" >&2
  exit 2
fi
for f in "$transcript" "$chunks" "$ingest"; do
  [[ -f "$f" ]] || { echo "broll-pick: not found: $f" >&2; exit 2; }
done

here="$(cd "$(dirname "$0")" && pwd)"
MT="${MCPTUBE_BIN:-$HOME/.local/pipx/venvs/mcptube/bin/mcptube}"
YTDLP="${MCPTUBE_YTDLP:-$HOME/.local/pipx/venvs/mcptube/bin/yt-dlp}"
CAP="${BROLL_VISION_CAP:-16}"
broll_dir="$(cd "$(dirname "$ingest")" && pwd)/broll"
# per-clip slot prefix: the broll dir is shared across every span of a run, so
# filenames MUST be namespaced by the plan they belong to or one span's footage
# overwrites another's slot (cross-span contamination — shorts-6u4).
slot_base="$(basename "$out")"; slot_base="${slot_base%.broll_plan.json}"
[[ -n "$slot_base" && "$slot_base" != "$(basename "$out")" ]] || slot_base="broll"

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
chunks_m="$(mtime "$chunks")"
sig="$(mtime "$transcript")|$chunks_m|$(mtime "$ingest")|v1"
meta="$out.pickmeta"

if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "broll-pick: cache hit at $out" >&2
  echo "$out"; exit 0
fi

mkdir -p "$(dirname "$out")"

empty_plan() {
  python3 "$here/emit_plan.py" /dev/null /dev/null 0 "$CAP" "$chunks_m" "$out" >/dev/null
  printf '%s' "$sig" > "$meta"
  echo "$out"
}

if [[ "${BROLL_PICK:-1}" == "0" ]]; then
  echo "broll-pick: disabled via BROLL_PICK=0" >&2
  empty_plan; exit 0
fi
[[ -x "$MT" ]] || { echo "broll-pick: mcptube not found at $MT; empty plan" >&2; empty_plan; exit 0; }
[[ -x "$YTDLP" ]] || { echo "broll-pick: yt-dlp not found at $YTDLP; empty plan" >&2; empty_plan; exit 0; }

src_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("url","").split("v=")[-1].split("&")[0][:16])' "$ingest" 2>/dev/null)"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
picks="$tmp/picks.jsonl"; : > "$picks"
ids="$tmp/ids.txt"; : > "$ids"
vcount="$tmp/vcount"; echo 0 > "$vcount"

# 1) anchor pick (one text claude call)
python3 "$here/pick_anchors.py" "$transcript" "$chunks" "$ingest" > "$tmp/anchor_prompt.txt"
if ! run_claude_step broll-pick-anchors "$tmp/anchor_prompt.txt" "$tmp/anchor_reply.txt" 2>"$tmp/aerr"; then
  echo "broll-pick: anchor claude step failed" >&2; cat "$tmp/aerr" >&2
  : > "$tmp/anchor_reply.txt"
fi
python3 "$here/parse_anchors.py" "$tmp/anchor_reply.txt" "$chunks" > "$tmp/windows.json"

nwin="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["windows"]))' "$tmp/windows.json")"
echo "broll-pick: $nwin candidate windows" >&2
if [[ "$nwin" -eq 0 ]]; then empty_plan; exit 0; fi

mkdir -p "$broll_dir"
nn=0

# frame-sample helper: writes a 3-frame hstack grid for video_id at 25/50/75% dur.
# echoes "<grid_path>\t<ts0>,<ts1>,<ts2>" on success, empty on failure.
sample_grid() {
  local vid="$1" dur="$2" gout="$3"
  read -r ta tb tc < <(python3 -c "
d=float('$dur'); lo=min(2.0,d*0.1); hi=max(lo,d-2.0)
import sys
ts=[lo+(hi-lo)*f for f in (0.25,0.5,0.75)]
print(' '.join(f'{t:.2f}' for t in ts))")
  local f0 f1 f2 i=0
  local paths=()
  for t in "$ta" "$tb" "$tc"; do
    local p
    p="$("$MT" frame "$vid" "$t" 2>/dev/null | grep -oE '/[^ ]+\.jpg' | head -1)"
    [[ -f "$p" ]] || return 1
    paths+=("$p")
  done
  ffmpeg -y -hide_banner -loglevel error \
    -i "${paths[0]}" -i "${paths[1]}" -i "${paths[2]}" \
    -filter_complex "[0:v]scale=360:-2[a];[1:v]scale=360:-2[b];[2:v]scale=360:-2[c];[a][b][c]hstack=inputs=3" \
    "$gout" 2>/dev/null || return 1
  printf '%s\t%s,%s,%s' "$ta" "$tb" "$tc" >/dev/null
  echo -e "$gout\t$ta,$tb,$tc"
}

# try a single candidate for a window+query. echoes "s0 s1 vid title url dur tsbest" on accept.
try_candidate() {
  local topic="$1" query="$2" winlen="$3" context="${4:-}"
  # keyless discovery
  local cands
  cands="$("$YTDLP" "ytsearch4:$query" --flat-playlist \
            --print "%(id)s|%(title)s|%(duration)s|%(webpage_url)s" 2>/dev/null)"
  [[ -z "$cands" ]] && return 1
  while IFS='|' read -r cid ctitle cdur curl; do
    [[ -z "$cid" ]] && continue
    [[ -n "$src_id" && "$cid" == "$src_id" ]] && continue   # never the podcast source
    # bound add cost: skip absurdly long videos
    python3 -c "import sys; d=sys.argv[1]; sys.exit(0 if (d not in ('','NA','None') and 5<=float(d)<=1500) else 1)" "$cdur" 2>/dev/null || continue
    [[ "$(cat "$vcount")" -ge "$CAP" ]] && return 2
    # ingest into mcptube (records id for cleanup)
    "$MT" add "$curl" >/dev/null 2>&1 || continue
    echo "$cid" >> "$ids"
    local gridinfo grid tsline
    gridinfo="$(sample_grid "$cid" "$cdur" "$tmp/grid_${cid}.jpg")" || { continue; }
    grid="${gridinfo%%	*}"; tsline="${gridinfo##*	}"
    python3 "$here/verify_prompt.py" "$topic" "$query" "$grid" "$tsline" "$context" > "$tmp/vp.txt"
    echo $(( $(cat "$vcount") + 1 )) > "$vcount"
    run_claude_step "broll-verify-$cid" "$tmp/vp.txt" "$tmp/vr.txt" 2>/dev/null || : > "$tmp/vr.txt"
    local verd; verd="$(python3 "$here/parse_verify.py" "$tmp/vr.txt")"
    local match best
    match="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1]).get("match"))' "$verd")"
    [[ "$match" != "True" ]] && continue
    best="$(python3 -c 'import json,sys;print(json.loads(sys.argv[1]).get("best",0))' "$verd")"
    # best frame's source timestamp -> center the segment there
    local tsbest s0 s1
    tsbest="$(echo "$tsline" | cut -d, -f$((best+1)))"
    read -r s0 s1 < <(python3 -c "
c=float('$tsbest'); L=float('$winlen'); d=float('$cdur')
s0=max(0.0,c-L/2); s1=min(d,s0+L+0.3)
if s1-s0 < L: s0=max(0.0,s1-L-0.3)
print(f'{s0:.2f} {s1:.2f}')")
    echo "$s0 $s1 $cid|$ctitle|$curl"
    return 0
  done <<< "$cands"
  return 1
}

# 2) per window: discover -> add -> frame -> verify, query rewrite once on miss
python3 -c '
import json,sys
for w in json.load(open(sys.argv[1]))["windows"]:
    print("\t".join([w["topic"],w["anchor_word"],w["query"],str(w["t0"]),str(w["t1"])]))
' "$tmp/windows.json" > "$tmp/winlist.tsv"

while IFS=$'\t' read -r topic anchor query t0 t1; do
  [[ "$(cat "$vcount")" -ge "$CAP" ]] && { echo "broll-pick: vision cap $CAP reached; dropping remaining" >&2; break; }
  winlen="$(python3 -c "print(round(float('$t1')-float('$t0'),3))")"
  # spoken text during this window — gives the verifier narrative context so it
  # can reject literal-but-wrong footage (cat laser vs sniper dot).
  context="$(python3 -c '
import json,sys
tx=json.load(open(sys.argv[1])); a,b=float(sys.argv[2]),float(sys.argv[3])
ws=[str(w.get("w","")).strip() for w in tx.get("words",[]) if a-0.3<=w.get("t0",0)<=b+0.3]
print(" ".join(ws)[:240])' "$transcript" "$t0" "$t1" 2>/dev/null)"
  res="$(try_candidate "$topic" "$query" "$winlen" "$context")"; rc=$?
  if [[ $rc -ne 0 || -z "$res" ]]; then
    # rewrite query once (ask Claude for one alternate phrasing)
    echo "Give ONE alternate YouTube search query (2-6 words) for B-roll of: $topic. Flip literal<->metaphorical or abstract<->embodied vs the failed query \"$query\". Output ONLY the query, no quotes, no prose." > "$tmp/rw.txt"
    run_claude_step "broll-rewrite" "$tmp/rw.txt" "$tmp/rw_out.txt" 2>/dev/null || : > "$tmp/rw_out.txt"
    q2="$(head -1 "$tmp/rw_out.txt" | tr -d '"' | sed 's/^ *//;s/ *$//')"
    [[ -z "$q2" ]] && { echo "broll-pick: drop window '$topic' (no rewrite)" >&2; continue; }
    res="$(try_candidate "$topic" "$q2" "$winlen" "$context")"; rc=$?
    query="$q2"
    if [[ $rc -ne 0 || -z "$res" ]]; then echo "broll-pick: drop window '$topic' (2nd miss)" >&2; continue; fi
  fi
  # res = "s0 s1 cid|title|url"
  s0="$(echo "$res" | awk '{print $1}')"
  s1="$(echo "$res" | awk '{print $2}')"
  srcinfo="$(echo "$res" | cut -d' ' -f3-)"
  cid="${srcinfo%%|*}"; rest="${srcinfo#*|}"; ctitle="${rest%%|*}"; curl="${rest##*|}"
  nn=$((nn+1))
  slot="$(printf '%s/%s_broll_%02d' "$broll_dir" "$slot_base" "$nn")"
  rm -f "$slot".* 2>/dev/null
  # download into a %(ext)s template — the merged best-format often lands as
  # .webm/.mkv, not .mp4. Capture whatever real file results and point
  # clip_path at it, so broll-composite's os.path.exists check never misses
  # (shorts-2xz: the bare broll_NN.mp4 path never existed -> all cutaways dropped).
  if ! "$YTDLP" --download-sections "*${s0}-${s1}" --force-keyframes-at-cuts \
        --merge-output-format mp4 \
        -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best" \
        -o "$slot.%(ext)s" "$curl" >/dev/null 2>&1; then
    echo "broll-pick: download failed for $topic; dropping" >&2
    nn=$((nn-1)); continue
  fi
  clip="$(ls "$slot".* 2>/dev/null | head -1)"
  [[ -n "$clip" && -f "$clip" ]] || { echo "broll-pick: no file after download; dropping" >&2; nn=$((nn-1)); continue; }
  python3 -c '
import json,sys
t0,t1,s0,s1,topic,anchor,query,cid,title,url,clip=sys.argv[1:12]
print(json.dumps({
  "t0":float(t0),"t1":float(t1),"topic":topic,"anchor_word":anchor,"query":query,
  "clip_path":clip,
  "source":{"video_id":cid,"title":title,"url":url,"t0_src":float(s0),"t1_src":float(s1)},
  "verified":True}))
' "$t0" "$t1" "$s0" "$s1" "$topic" "$anchor" "$query" "$cid" "$ctitle" "$curl" "$clip" >> "$picks"
  echo "broll-pick: + $topic [$t0-$t1] <- $cid [$s0-$s1] $clip" >&2
done < "$tmp/winlist.tsv"

python3 "$here/emit_plan.py" "$picks" "$ids" "$(cat "$vcount")" "$CAP" "$chunks_m" "$out" >/dev/null
printf '%s' "$sig" > "$meta"
echo "broll-pick: wrote $out (picks=$(wc -l < "$picks" | tr -d ' '), vision=$(cat "$vcount"))" >&2
echo "$out"
