#!/usr/bin/env bash
# broll-pick: Claude picks visualizable anchors; mcptube/yt-dlp source candidate
# footage; Claude vision-verifies candidates; chosen segments download into
# work/<id>/broll/. Emits broll_plan.json. No API key (Claude via host/pane).
#
# Round-based engine (shorts-wqm — pane round-trips dominated wall-clock):
#   each round, every unresolved window nominates its next untried candidate;
#   candidate prep (mcptube add + frame grid) runs CONCURRENTLY; then ONE
#   batched vision call judges up to BROLL_BATCH candidates at once. Misses
#   advance to the window's next candidate; an exhausted query gets ONE
#   rewrite (batched across windows), then the window drops. The vision
#   budget (BROLL_VISION_CAP) counts candidates judged, not calls, so
#   batching keeps the same effective budget in ~1/4 the round-trips.
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
BATCH="${BROLL_BATCH:-4}"
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
ids="$tmp/ids.txt"; : > "$ids"

# block while >= $1 background jobs are live (bash 3.2: no wait -n)
gate() {
  while (( $(jobs -rp | wc -l) >= $1 )); do sleep 0.2; done
}

# 1) anchor pick (one text claude call)
python3 "$here/pick_anchors.py" "$transcript" "$chunks" "$ingest" > "$tmp/anchor_prompt.txt"
if ! run_claude_step broll-pick-anchors "$tmp/anchor_prompt.txt" "$tmp/anchor_reply.txt" 2>"$tmp/aerr"; then
  echo "broll-pick: anchor claude step failed" >&2; cat "$tmp/aerr" >&2
  : > "$tmp/anchor_reply.txt"
fi
python3 "$here/parse_anchors.py" "$tmp/anchor_reply.txt" "$chunks" > "$tmp/windows.json"

# window table: topic, anchor, query, t0, t1, len, spoken context (one python
# pass; tabs/newlines stripped so the TSV stays sane)
python3 - "$tmp/windows.json" "$transcript" > "$tmp/winlist.tsv" <<'PY'
import json, sys
wins = json.load(open(sys.argv[1]))["windows"]
tx = json.load(open(sys.argv[2]))
words = tx.get("words", [])
def clean(s): return " ".join(str(s).split())
for w in wins:
    a, b = float(w["t0"]), float(w["t1"])
    ws = [str(x.get("w", "")).strip() for x in words if a - 0.3 <= x.get("t0", 0) <= b + 0.3]
    print("\t".join([
        clean(w["topic"]), clean(w["anchor_word"]), clean(w["query"]),
        str(a), str(b), f"{b - a:.3f}", clean(" ".join(ws))[:240],
    ]))
PY

# per-window state (bash 3.2: parallel indexed arrays, no declare -A)
W_TOPIC=(); W_ANCHOR=(); W_QUERY=(); W_T0=(); W_T1=(); W_LEN=(); W_CTX=()
W_STATE=(); W_ATTEMPT=(); W_TRIED=(); W_CAND=(); W_PICK=()
nwin=0
while IFS=$'\t' read -r topic anchor query t0 t1 wlen ctx; do
  [[ -z "$topic" || -z "$query" ]] && continue
  W_TOPIC[$nwin]="$topic"; W_ANCHOR[$nwin]="$anchor"; W_QUERY[$nwin]="$query"
  W_T0[$nwin]="$t0"; W_T1[$nwin]="$t1"; W_LEN[$nwin]="$wlen"; W_CTX[$nwin]="$ctx"
  W_STATE[$nwin]=pending; W_ATTEMPT[$nwin]=0; W_TRIED[$nwin]=""; W_CAND[$nwin]=""; W_PICK[$nwin]=""
  nwin=$((nwin + 1))
done < "$tmp/winlist.tsv"

echo "broll-pick: $nwin candidate windows" >&2
if [[ "$nwin" -eq 0 ]]; then empty_plan; exit 0; fi

mkdir -p "$broll_dir"

# keyless ytsearch, cached per query; echoes the cache file path
search_cache() {
  local q="$1" key f
  key="$(printf '%s' "$q" | md5 -q 2>/dev/null || printf '%s' "$q" | md5sum | cut -d' ' -f1)"
  f="$tmp/search_$key.tsv"
  if [[ ! -e "$f" ]]; then
    "$YTDLP" "ytsearch4:$q" --flat-playlist \
      --print "%(id)s|%(title)s|%(duration)s|%(webpage_url)s" 2>/dev/null > "$f" || : > "$f"
  fi
  [[ -s "$f" ]] || return 1
  printf '%s\n' "$f"
}

# next untried, sane-duration candidate for window $1: "cid|title|dur|url"
next_candidate() {
  local i="$1" sf cid ctitle cdur curl
  sf="$(search_cache "${W_QUERY[$i]}")" || return 1
  while IFS='|' read -r cid ctitle cdur curl; do
    [[ -z "$cid" ]] && continue
    [[ -n "$src_id" && "$cid" == "$src_id" ]] && continue   # never the podcast source
    [[ " ${W_TRIED[$i]} " == *" $cid "* ]] && continue
    # bound add cost: skip absurdly long videos
    python3 -c "import sys; d=sys.argv[1]; sys.exit(0 if (d not in ('','NA','None') and 5<=float(d)<=1500) else 1)" "$cdur" 2>/dev/null || continue
    printf '%s|%s|%s|%s\n' "$cid" "$ctitle" "$cdur" "$curl"
    return 0
  done < "$sf"
  return 1
}

# frame-sample helper: writes a 3-frame hstack grid for video_id at 25/50/75% dur.
# echoes "<grid_path>\t<ts0>,<ts1>,<ts2>" on success, empty on failure.
sample_grid() {
  local vid="$1" dur="$2" gout="$3"
  local ta tb tc
  read -r ta tb tc < <(python3 -c "
d=float('$dur'); lo=min(2.0,d*0.1); hi=max(lo,d-2.0)
ts=[lo+(hi-lo)*f for f in (0.25,0.5,0.75)]
print(' '.join(f'{t:.2f}' for t in ts))")
  local t p
  local paths=()
  for t in "$ta" "$tb" "$tc"; do
    p="$("$MT" frame "$vid" "$t" 2>/dev/null | grep -oE '/[^ ]+\.jpg' | head -1)"
    [[ -f "$p" ]] || return 1
    paths+=("$p")
  done
  ffmpeg -y -hide_banner -loglevel error \
    -i "${paths[0]}" -i "${paths[1]}" -i "${paths[2]}" \
    -filter_complex "[0:v]scale=360:-2[a];[1:v]scale=360:-2[b];[2:v]scale=360:-2[c];[a][b][c]hstack=inputs=3" \
    "$gout" 2>/dev/null || return 1
  echo -e "$gout\t$ta,$tb,$tc"
}

# warm every original query's search cache concurrently (network-bound)
for ((i = 0; i < nwin; i++)); do
  gate 6
  ( search_cache "${W_QUERY[$i]}" >/dev/null 2>&1 || true ) &
done
wait

vused=0
round=0
while :; do
  round=$((round + 1))
  (( round > 50 )) && break   # belt-and-braces against state-machine bugs

  # vision budget exhausted -> drop everything unresolved
  if (( vused >= CAP )); then
    for ((i = 0; i < nwin; i++)); do
      case "${W_STATE[$i]}" in pending|rewrite)
        W_STATE[$i]=dropped
        echo "broll-pick: drop window '${W_TOPIC[$i]}' (vision cap $CAP)" >&2 ;;
      esac
    done
    break
  fi

  # batched query rewrites: every window whose first query exhausted, one call
  rw=()
  for ((i = 0; i < nwin; i++)); do
    [[ "${W_STATE[$i]}" == rewrite ]] && rw+=("$i")
  done
  if (( ${#rw[@]} > 0 )); then
    {
      echo "You are sourcing B-roll footage. For each numbered item give ONE alternate YouTube search query (2-6 words). Flip literal<->metaphorical or abstract<->embodied vs the failed query."
      for i in "${rw[@]}"; do
        echo "ITEM $i: footage of ${W_TOPIC[$i]}; failed query \"${W_QUERY[$i]}\""
      done
      echo 'Return ONLY one JSON object on a single line, no prose: {"rewrites":[{"n":<item number>,"query":"..."}, ...]}'
    } > "$tmp/rw.txt"
    run_claude_step "broll-rewrites-r$round" "$tmp/rw.txt" "$tmp/rw_out.txt" 2>/dev/null || : > "$tmp/rw_out.txt"
    python3 - "$tmp/rw_out.txt" > "$tmp/rw_parsed.tsv" <<'PY'
import json, re, sys
reply = open(sys.argv[1]).read()
m = re.search(r"\{.*\}", reply, re.DOTALL)
if m:
    try:
        for r in json.loads(m.group(0)).get("rewrites", []) or []:
            try:
                n = int(r.get("n"))
            except Exception:
                continue
            q = " ".join(str(r.get("query", "")).split()).strip('"').strip()
            if q:
                print(f"{n}\t{q}")
    except Exception:
        pass
PY
    for i in "${rw[@]}"; do
      q2="$(awk -F'\t' -v n="$i" '$1 == n {print $2; exit}' "$tmp/rw_parsed.tsv")"
      if [[ -n "$q2" ]]; then
        W_QUERY[$i]="$q2"; W_ATTEMPT[$i]=1; W_STATE[$i]=pending
      else
        W_STATE[$i]=dropped
        echo "broll-pick: drop window '${W_TOPIC[$i]}' (no rewrite)" >&2
      fi
    done
  fi

  # nominate this round's batch: each pending window's next untried candidate
  batch=()
  for ((i = 0; i < nwin; i++)); do
    [[ "${W_STATE[$i]}" == pending ]] || continue
    (( ${#batch[@]} >= BATCH )) && break
    (( vused + ${#batch[@]} >= CAP )) && break
    if cand="$(next_candidate "$i")"; then
      W_CAND[$i]="$cand"
      batch+=("$i")
    elif (( ${W_ATTEMPT[$i]} == 0 )); then
      W_STATE[$i]=rewrite
    else
      W_STATE[$i]=dropped
      echo "broll-pick: drop window '${W_TOPIC[$i]}' (2nd miss)" >&2
    fi
  done

  if (( ${#batch[@]} == 0 )); then
    # anything left is mid-rewrite (handled next round) or resolved
    pending_left=0
    for ((i = 0; i < nwin; i++)); do
      case "${W_STATE[$i]}" in pending|rewrite) pending_left=1 ;; esac
    done
    (( pending_left )) && continue
    break
  fi

  # concurrent prep: mcptube ingest + 3-frame grid per nominated candidate.
  # Tried-marking happens HERE in the parent (subshells can't mutate arrays).
  for i in "${batch[@]}"; do
    IFS='|' read -r cid ctitle cdur curl <<< "${W_CAND[$i]}"
    W_TRIED[$i]="${W_TRIED[$i]} $cid"
    rm -f "$tmp/prep_$i.tsv"
    (
      # one retry: concurrent adds can transiently contend on mcptube's db
      if ! "$MT" add "$curl" >/dev/null 2>&1; then
        sleep 2
        "$MT" add "$curl" >/dev/null 2>&1 || exit 1
      fi
      echo "$cid" >> "$ids"
      gridinfo="$(sample_grid "$cid" "$cdur" "$tmp/grid_${i}_${cid}.jpg")" || exit 1
      printf '%s|%s|%s|%s\t%s\n' "$cid" "$ctitle" "$cdur" "$curl" "$gridinfo" > "$tmp/prep_$i.tsv"
    ) &
  done
  wait

  # manifest of successfully prepped candidates -> one batched vision call
  : > "$tmp/manifest_in.tsv"
  judged=()
  for i in "${batch[@]}"; do
    [[ -s "$tmp/prep_$i.tsv" ]] || continue   # prep failed: stays pending, next candidate next round
    judged+=("$i")
    IFS=$'\t' read -r candinfo grid tsline < "$tmp/prep_$i.tsv"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$i" "${W_TOPIC[$i]}" "${W_QUERY[$i]}" "${W_CTX[$i]}" "$grid" "$tsline" >> "$tmp/manifest_in.tsv"
  done
  (( ${#judged[@]} == 0 )) && continue
  vused=$((vused + ${#judged[@]}))

  python3 - "$tmp/manifest_in.tsv" "$tmp/manifest.json" <<'PY'
import json, sys
man = []
for line in open(sys.argv[1]):
    n, topic, query, ctx, grid, ts = line.rstrip("\n").split("\t")
    man.append({"n": int(n), "topic": topic, "query": query, "context": ctx, "grid": grid, "ts": ts})
json.dump(man, open(sys.argv[2], "w"))
PY
  python3 "$here/verify_batch_prompt.py" "$tmp/manifest.json" > "$tmp/vp.txt"
  run_claude_step "broll-verify-r$round" "$tmp/vp.txt" "$tmp/vr.txt" 2>/dev/null || : > "$tmp/vr.txt"
  verdicts="$(python3 "$here/parse_verify_batch.py" "$tmp/vr.txt")"
  echo "broll-pick: round $round judged ${#judged[@]} candidate(s) in one call (vision $vused/$CAP)" >&2

  for i in "${judged[@]}"; do
    read -r match best < <(python3 -c '
import json, sys
r = json.loads(sys.argv[1]).get(sys.argv[2], {})
print(r.get("match"), r.get("best", 0))' "$verdicts" "$i")
    [[ "$match" != "True" ]] && continue   # miss: next candidate next round
    IFS='|' read -r cid ctitle cdur curl <<< "${W_CAND[$i]}"
    IFS=$'\t' read -r candinfo grid tsline < "$tmp/prep_$i.tsv"
    tsbest="$(echo "$tsline" | cut -d, -f$((best + 1)))"
    read -r s0 s1 < <(python3 -c "
c=float('$tsbest'); L=float('${W_LEN[$i]}'); d=float('$cdur')
s0=max(0.0,c-L/2); s1=min(d,s0+L+0.3)
if s1-s0 < L: s0=max(0.0,s1-L-0.3)
print(f'{s0:.2f} {s1:.2f}')")
    W_PICK[$i]="$s0|$s1|$cid|$ctitle|$curl"
    W_STATE[$i]=accepted
    echo "broll-pick: + ${W_TOPIC[$i]} [${W_T0[$i]}-${W_T1[$i]}] <- $cid [$s0-$s1]" >&2
  done
done

# concurrent section downloads for every accepted window (waves of 4)
nn=0
for ((i = 0; i < nwin; i++)); do
  [[ "${W_STATE[$i]}" == accepted ]] || continue
  nn=$((nn + 1))
  slot="$(printf '%s/%s_broll_%02d' "$broll_dir" "$slot_base" "$nn")"
  rm -f "$slot".* 2>/dev/null
  IFS='|' read -r s0 s1 cid ctitle curl <<< "${W_PICK[$i]}"
  gate 4
  (
    # download into a %(ext)s template — the merged best-format often lands as
    # .webm/.mkv, not .mp4. Capture whatever real file results and point
    # clip_path at it, so broll-composite's os.path.exists check never misses
    # (shorts-2xz: the bare broll_NN.mp4 path never existed -> all cutaways dropped).
    if ! "$YTDLP" --download-sections "*${s0}-${s1}" --force-keyframes-at-cuts \
          --merge-output-format mp4 \
          -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best" \
          -o "$slot.%(ext)s" "$curl" >/dev/null 2>&1; then
      echo "broll-pick: download failed for ${W_TOPIC[$i]}; dropping" >&2
      exit 1
    fi
    clip="$(ls "$slot".* 2>/dev/null | head -1)"
    [[ -n "$clip" && -f "$clip" ]] || { echo "broll-pick: no file after download; dropping" >&2; exit 1; }
    python3 -c '
import json,sys
t0,t1,s0,s1,topic,anchor,query,cid,title,url,clip=sys.argv[1:12]
print(json.dumps({
  "t0":float(t0),"t1":float(t1),"topic":topic,"anchor_word":anchor,"query":query,
  "clip_path":clip,
  "source":{"video_id":cid,"title":title,"url":url,"t0_src":float(s0),"t1_src":float(s1)},
  "verified":True}))
' "${W_T0[$i]}" "${W_T1[$i]}" "$s0" "$s1" "${W_TOPIC[$i]}" "${W_ANCHOR[$i]}" "${W_QUERY[$i]}" \
  "$cid" "$ctitle" "$curl" "$clip" > "$tmp/pick_$i.json"
    echo "broll-pick: + downloaded ${W_TOPIC[$i]} -> $clip" >&2
  ) &
done
wait

picks="$tmp/picks.jsonl"; : > "$picks"
for ((i = 0; i < nwin; i++)); do
  [[ -s "$tmp/pick_$i.json" ]] && cat "$tmp/pick_$i.json" >> "$picks"
done

python3 "$here/emit_plan.py" "$picks" "$ids" "$vused" "$CAP" "$chunks_m" "$out" >/dev/null
printf '%s' "$sig" > "$meta"
echo "broll-pick: wrote $out (picks=$(wc -l < "$picks" | tr -d ' '), vision=$vused)" >&2
echo "$out"
