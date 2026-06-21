#!/usr/bin/env bash
# director-pass: an agentic, vision-driven final QA/repair pass. A Claude instance
# WATCHES the finished short (a contact sheet of frames across the whole clip +
# the transcript + the sidecar plans) and decides, in natural language, what is
# broken ANYWHERE — not just the cold open, not just a fixed route vocabulary.
# It then APPLIES the fixes it can from a bounded, pixel-safe set (tail_trim via
# cut-clip; music_down via a bg-music re-mix) and SURFACES everything else as an
# honest edit list, re-reviewing up to DIRECTOR_MAX_ITERS times.
#
# Layered ON TOP of grade-clip (the cheap proxy floor) + fix-cold-open (the
# closed-vocab cold-open repair): this is the expensive open-ended per-clip loop.
#
# Two modes (like fix-cold-open):
#   preventive (in-chain): clip_NN.* sidecars + the pre-mix .ctaed.mp4 are co-
#     located in work/<id>/, so music_down can re-mix; tail_trim is always clean.
#   curative (standalone/backlog): a finished output/<src>/x.mp4 -> tail_trim only
#     (pixel-safe), everything else surfaced (never fabricate a baked-in repair).
#
# NON-FATAL: any error leaves the input untouched, exit 0. Idempotent (.dpmeta).
#   director-pass.sh <clip.mp4> [--pane <p>]      single / in-chain
#   director-pass.sh --backlog [output_dir]        sweep output/ -> _director.json
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }

MAXIT="${DIRECTOR_MAX_ITERS:-1}"
NFR="${DIRECTOR_FRAMES:-12}"
MINDUR="${DIRECTOR_MIN_DUR:-15}"
VOL="${DIRECTOR_BED_VOL:-0.17}"

skill_sh() { echo "$(cd "$here/../$1" && pwd)/$1.sh"; }
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
probe_dur() { ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 "$1" 2>/dev/null; }

# directone <clip> -> writes <stem>.director.json (+ <stem>.dir.mp4 if repaired).
# echoes the report path. Never fatal.
directone() {
  local clip="$1"
  [[ -f "$clip" ]] || { echo "director-pass: not found: $clip" >&2; return 1; }

  local d base ccore stem report out meta
  d="$(cd "$(dirname "$clip")" && pwd)"
  base="$(basename "$clip")"
  stem="${clip%.*}"
  ccore=""
  [[ "$base" =~ ^(clip_[0-9]+)\. ]] && ccore="${BASH_REMATCH[1]}"
  report="$stem.director.json"
  out="$stem.dir.mp4"

  # ---- resolve sidecars -----------------------------------------------------
  local tx="" chunks="" fill="" broll="" cad="" title="" mood="" grade="" ctaed="" ingest=""
  if [[ -n "$ccore" ]]; then
    for f in "$d/$ccore.tight.transcript.json" "$d/$ccore.transcript.json"; do [[ -f "$f" ]] && { tx="$f"; break; }; done
    [[ -f "$d/$ccore.chunks.json" ]] && chunks="$d/$ccore.chunks.json"
    for f in "$d/$ccore.vert.fillplan.json" "$d/$ccore.fillplan.json"; do [[ -f "$f" ]] && { fill="$f"; break; }; done
    [[ -f "$d/$ccore.broll_plan.json" ]] && broll="$d/$ccore.broll_plan.json"
    [[ -f "$d/$ccore.cadence.json" ]] && cad="$d/$ccore.cadence.json"
    [[ -f "$d/$ccore.title.txt" ]] && title="$d/$ccore.title.txt"
    [[ -f "$d/$ccore.mood.txt" ]] && mood="$d/$ccore.mood.txt"
    [[ -f "$d/$ccore.ctaed.mp4" ]] && ctaed="$d/$ccore.ctaed.mp4"
    [[ -f "$d/ingest.json" ]] && ingest="$d/ingest.json"
    for g in "$stem.grade.json" "$d/$ccore.grade.json" "$d/$ccore.final.grade.json"; do [[ -f "$g" ]] && { grade="$g"; break; }; done
  else
    [[ -f "$stem.grade.json" ]] && grade="$stem.grade.json"
  fi

  # ---- mode -----------------------------------------------------------------
  local mode="${DIRECTOR_MODE:-auto}"
  if [[ "$mode" == "auto" ]]; then
    if [[ -n "$ccore" && ( -n "$ctaed" || -n "$broll" || -n "$chunks" ) ]]; then mode="preventive"; else mode="curative"; fi
  fi

  # ---- idempotency ----------------------------------------------------------
  local sig; sig="$(mtime "$clip")"
  local f
  for f in "$tx" "$chunks" "$fill" "$broll" "$cad" "$title" "$mood" "$grade"; do
    [[ -n "$f" && -f "$f" ]] && sig="$sig|$(mtime "$f")"
  done
  sig="$sig|max=$MAXIT|n=$NFR|min=$MINDUR|vol=$VOL|mode=$mode|v1"
  meta="$report.dpmeta"
  if [[ -f "$report" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
    echo "director-pass: cache hit at $report" >&2
    echo "$report"; return 0
  fi

  if [[ "${DIRECTOR_PASS:-1}" == "0" ]]; then
    printf '{"clip":"%s","mode":"%s","verdict":"disabled","iterations":0,"applied":[],"surfaced":[],"output":"%s","rerun_recommended":false}\n' "$clip" "$mode" "$clip" > "$report"
    printf '%s' "$sig" > "$meta"
    echo "$report"; return 0
  fi

  local dur; dur="$(probe_dur "$clip")"
  if [[ -z "$dur" ]] || ! python3 -c "import sys;sys.exit(0 if float('$dur')>1 else 1)" 2>/dev/null; then
    printf '{"clip":"%s","mode":"%s","verdict":"ship","summary":"unreadable duration","iterations":0,"applied":[],"surfaced":[],"output":"%s","rerun_recommended":false}\n' "$clip" "$mode" "$clip" > "$report"
    printf '%s' "$sig" > "$meta"
    echo "$report"; return 0
  fi

  echo "director-pass: mode=$mode dur=${dur}s clip=$base" >&2
  local tmp; tmp="$(mktemp -d)"
  local work="$clip"
  local applied="$tmp/applied.jsonl"; : > "$applied"
  local surfaced="$tmp/surfaced.jsonl"; : > "$surfaced"
  local verdict="ship" summary="" iters=0

  local it
  for ((it=1; it<=MAXIT; it++)); do
    iters="$it"
    local wd; wd="$(probe_dur "$work")"; [[ -z "$wd" ]] && wd="$dur"
    local sub="$tmp/it$it"; mkdir -p "$sub"

    # 1) contact sheet
    local sheetjson; sheetjson="$(python3 "$here/frames.py" "$work" "$sub" --n "$NFR" 2>/dev/null)"
    local sheet; sheet="$(printf '%s' "$sheetjson" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("sheet",""))
except Exception: print("")' 2>/dev/null)"
    if [[ -z "$sheet" || ! -f "$sheet" ]]; then
      echo "director-pass: contact sheet build failed (iter $it) — ship" >&2
      break
    fi
    printf '%s' "$sheetjson" > "$sub/frames.json"

    # 2) prompt
    python3 "$here/build_prompt.py" "$work" "$wd" "$sheet" "$sub/frames.json" \
      --transcript "$tx" --chunks "$chunks" --fill "$fill" --broll "$broll" \
      --cadence "$cad" --title "$title" --mood "$mood" --grade "$grade" \
      --mode "$mode" --vol "$VOL" --mindur "$MINDUR" > "$sub/prompt.txt" 2>/dev/null || {
        echo "director-pass: prompt build failed — ship" >&2; break; }

    # 3) Claude vision review (non-fatal). DIRECTOR_REPLY_FILE is a test seam:
    # when set, the canned reply stands in for the live model (offline proof).
    if [[ -n "${DIRECTOR_REPLY_FILE:-}" && -f "$DIRECTOR_REPLY_FILE" ]]; then
      cp "$DIRECTOR_REPLY_FILE" "$sub/reply.txt"
    elif ! run_claude_step director-pass "$sub/prompt.txt" "$sub/reply.txt" 2>"$sub/err"; then
      echo "director-pass: claude review unavailable (iter $it) — ship" >&2
      cat "$sub/err" >&2 || true
      break
    fi

    # 4) normalize + validate
    verdict="$(python3 "$here/parse_reply.py" normalize "$sub/reply.txt" "$wd" "$sub/review.json" --mode "$mode" --vol "$VOL" --mindur "$MINDUR" 2>/dev/null || echo ship)"
    summary="$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("summary","")[:240])
except Exception: print("")' "$sub/review.json" 2>/dev/null)"

    # collect surfaced ops from this review
    python3 -c 'import json,sys
try: doc=json.load(open(sys.argv[1]))
except Exception: doc={}
for o in doc.get("ops",[]):
    if o.get("op")=="surface":
        print(json.dumps(o))' "$sub/review.json" >> "$surfaced" 2>/dev/null || true

    if [[ "$verdict" == "ship" ]]; then
      echo "director-pass: verdict ship (iter $it)" >&2
      break
    fi

    # 5) apply the bounded ops (music re-mix first, then tail trim)
    python3 "$here/parse_reply.py" ops "$sub/review.json" > "$sub/ops.tsv" 2>/dev/null || : > "$sub/ops.tsv"
    local nbefore; nbefore="$(wc -l < "$applied" | tr -d ' ')"

    local mvol; mvol="$(grep -m1 '^music_down' "$sub/ops.tsv" 2>/dev/null | cut -f3 || true)"
    if [[ -n "$mvol" && "$mode" == "preventive" && -n "$ctaed" ]]; then
      local md; md="$(cat "$mood" 2>/dev/null || echo 'ALL SONGS')"
      local m1="$sub/music.mp4" m2="$sub/music.ended.mp4" m3="$sub/music.sped.mp4"
      if bash "$(skill_sh bg-music)" "$ctaed" "$m1" "$md" "$mvol" >/dev/null 2>&1 && [[ -f "$m1" ]] \
         && { bash "$(skill_sh end-card)" "$m1" "$m2" >/dev/null 2>&1 || cp "$m1" "$m2"; } \
         && { bash "$(skill_sh speed-up)" "$m2" "$m3" >/dev/null 2>&1 || cp "$m2" "$m3"; } \
         && [[ -f "$m3" ]]; then
        work="$m3"
        python3 -c 'import json,sys;print(json.dumps({"op":"music_down","volume":float(sys.argv[1]),"result":"re-mixed bed at "+sys.argv[1]}))' "$mvol" >> "$applied"
        echo "director-pass: music_down -> re-mixed bed at $mvol" >&2
      else
        echo "director-pass: music_down re-mix failed — skipped" >&2
        python3 -c 'import json;print(json.dumps({"op":"surface","kind":"music_loud","detail":"music_down re-mix failed","rerun_recommended":True}))' >> "$surfaced"
      fi
    fi

    local tt1; tt1="$(grep -m1 '^tail_trim' "$sub/ops.tsv" 2>/dev/null | cut -f2 || true)"
    if [[ -n "$tt1" ]]; then
      local cur; cur="$(probe_dur "$work")"; [[ -z "$cur" ]] && cur="$wd"
      # re-validate against the CURRENT working clip's duration
      if python3 -c "import sys;t=float('$tt1');d=float('$cur');sys.exit(0 if ${MINDUR%.*} <= t <= d-0.25 else 1)" 2>/dev/null; then
        local c1="$sub/trim.mp4" c2="$sub/trim.ended.mp4"
        if bash "$(skill_sh cut-clip)" "$work" 0 "$tt1" "$c1" true >/dev/null 2>&1 && [[ -f "$c1" ]]; then
          bash "$(skill_sh end-card)" "$c1" "$c2" >/dev/null 2>&1 || cp "$c1" "$c2"
          work="$c2"
          python3 -c 'import json,sys;print(json.dumps({"op":"tail_trim","t1":float(sys.argv[1]),"result":"trimmed tail to "+sys.argv[1]+"s + re-landed end-card"}))' "$tt1" >> "$applied"
          echo "director-pass: tail_trim -> cut to ${tt1}s" >&2
        else
          echo "director-pass: tail_trim cut-clip failed — skipped" >&2
        fi
      else
        echo "director-pass: tail_trim t1=$tt1 out of range vs ${cur}s — skipped" >&2
      fi
    fi

    local nafter; nafter="$(wc -l < "$applied" | tr -d ' ')"
    if [[ "$nafter" == "$nbefore" ]]; then
      echo "director-pass: nothing applied this iter — stop" >&2
      break
    fi
  done

  # ---- finalize -------------------------------------------------------------
  local outpath="$clip"
  if [[ "$work" != "$clip" && -f "$work" ]]; then
    cp "$work" "$out" && outpath="$out"
    echo "director-pass: wrote repaired clip -> $out" >&2
  fi

  python3 - "$report" "$clip" "$mode" "$iters" "$verdict" "$summary" "$outpath" "$applied" "$surfaced" <<'PY'
import json, sys
report, clip, mode, iters, verdict, summary, outpath, applied, surfaced = sys.argv[1:10]
def rows(p):
    out=[]
    try:
        for ln in open(p):
            ln=ln.strip()
            if ln:
                out.append(json.loads(ln))
    except Exception:
        pass
    return out
ap=rows(applied); su=rows(surfaced)
rerun=any(s.get("rerun_recommended") for s in su)
v="revised" if ap else ("revise" if su and verdict!="ship" else verdict)
doc={"clip":clip,"mode":mode,"iterations":int(iters or 0),"verdict":v,
     "summary":summary,"applied":ap,"surfaced":su,"output":outpath,
     "rerun_recommended":bool(rerun)}
json.dump(doc, open(report,"w"), indent=2)
sys.stderr.write(json.dumps({"verdict":v,"applied":len(ap),"surfaced":len(su),"output":outpath})+"\n")
PY

  printf '%s' "$sig" > "$meta"
  rm -rf "$tmp"
  echo "$report"
}

# ---- backlog ----------------------------------------------------------------
if [[ "${1:-}" == "--backlog" ]]; then
  outdir="${2:-${OUTPUT_DIR:-output}}"; outdir="${outdir%/}"
  [[ -d "$outdir" ]] || { echo "director-pass: backlog dir not found: $outdir" >&2; exit 0; }
  reports=()
  while IFS= read -r -u 3 mp4; do
    [[ -z "$mp4" ]] && continue
    case "$mp4" in */_preview/*|*/source/*|*/_toupload/*) continue;; esac
    r="$(directone "$mp4")" || continue
    reports+=("$r")
  done 3< <(find "$outdir" -type f -name '*.mp4' 2>/dev/null | sort)

  agg="$outdir/_director.json"
  python3 - "$agg" "${reports[@]+"${reports[@]}"}" <<'PY'
import sys, json, datetime
out=sys.argv[1]; paths=sys.argv[2:]
revised=[]; surfaced=[]; clean=[]
for p in paths:
    try: d=json.load(open(p))
    except Exception: continue
    c=d.get("clip",p)
    if d.get("applied"): revised.append({"clip":c,"applied":[a.get("op") for a in d["applied"]]})
    elif d.get("surfaced"): surfaced.append({"clip":c,"issues":[s.get("kind") for s in d["surfaced"]]})
    else: clean.append(c)
rep={"generated":datetime.datetime.now().isoformat(timespec="seconds"),
     "n":len(paths),"revised":revised,"surfaced":surfaced,"clean":clean}
json.dump(rep, open(out,"w"), indent=2)
print(json.dumps({"n":rep["n"],"revised":len(revised),"surfaced":len(surfaced),"clean":len(clean)}))
PY
  echo "director-pass: backlog -> $agg" >&2
  exit 0
fi

if [[ -z "${1:-}" ]]; then
  echo "usage: director-pass.sh <clip.mp4> [--pane <p>] | --backlog [output_dir]" >&2
  exit 2
fi

rep="$(directone "$1")" || exit 0
[[ -f "$rep" ]] && cat "$rep"
exit 0
