#!/usr/bin/env bash
# grade-clip: per-clip upload-readiness grade (0-99) read off a FINISHED .mp4 plus
# its persisted sidecar plans. The first skill that inspects a delivered pixel
# artifact for upload-readiness — the on-disk proxy for YouTube's VVSA swipe gate.
# Deterministic retention-proxy floor (frame1_is_face / letterbox / credit-at-open
# / first-visual-change / first-payoff / static-gap / opening-caption / residual-
# silence / terminal-loop) + hard caps (letterbox, face_withheld, credit_at_open,
# blocking_card, dead_tail) that cap grade<=40, then ONE batched Claude rubric call
# (skipped when GRADE_SKIP_CLAUDE=1). Emits <clip>.grade.json per the locked
# SELECTION-SUITE-CONTRACT.md schema.
#
# Two modes:
#   grade-clip.sh <clip.mp4>                  single / in-chain (after save-local)
#   grade-clip.sh --backlog [output_dir=output]  sweep output/<src>/*.mp4 + _triage.json
#
# NON-FATAL: any error -> DROSS/empty verdict, exit 0. Idempotent: mtime+param
# .gcmeta cache. GRADE_SKIP_CLAUDE=1 -> proxy-only (backlog default).
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }
source "$here/../_lib/pane.sh"

scene="${GRADE_SCENE:-0.3}"
minup="${GRADE_MIN_UPLOAD:-60}"

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }

# sig is over the clip mtime + the SPECIFIC input sidecars grade-clip consumes
# (never the output grade.json, or the signature would never stabilize). Hash
# their mtimes so re-running after fill/broll/chunks/cadence change re-grades.
gradesig() {
  local clip="$1" parts
  parts="$(mtime "$clip")"
  local d base stem f
  d="$(cd "$(dirname "$clip")" && pwd)"
  base="$(basename "$clip")"
  stem="${base%%.*}"
  for f in \
    "$d/$stem.vert.fillplan.json" "$d/$stem.fillplan.json" "${clip%.*}.fillplan.json" \
    "${clip%.*}.cadence.json" "$d/$stem.cadence.json" \
    "$d/$stem.chunks.json" "$d/$stem.broll_plan.json" "$d/$stem.title.txt" \
    "$d/$stem.tight.transcript.json" "$d/$stem.transcript.json" "$d/$stem.verify.json"; do
    [[ -f "$f" ]] && parts="$parts|$(mtime "$f")"
  done
  printf '%s|%s|%s|%s|v1' "$parts" "$minup" "${GRADE_SKIP_CLAUDE:-0}" "$scene"
}

# grade ONE clip -> writes <clip>.grade.json. Echoes the path. Never fatal.
gradeone() {
  local clip="$1"
  [[ -f "$clip" ]] || { echo "grade-clip: not found: $clip" >&2; return 1; }
  local out="${clip%.*}.grade.json"
  local meta="$out.gcmeta"
  local sig; sig="$(gradesig "$clip")"
  if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
    echo "grade-clip: cache hit at $out" >&2
    echo "$out"; return 0
  fi

  local skip=()
  [[ "${GRADE_SKIP_CLAUDE:-0}" == "1" ]] && skip=(--skip-claude)

  # locate the transcript + title for the optional Claude rubric (in-chain only;
  # finished output clips usually lack them -> proxy-only).
  local d base stem tx title cjson=""
  d="$(cd "$(dirname "$clip")" && pwd)"
  base="$(basename "$clip")"; stem="${base%%.*}"
  tx=""; title=""
  for f in "$d/$stem.tight.transcript.json" "$d/$stem.transcript.json"; do
    [[ -f "$f" ]] && { tx="$f"; break; }
  done
  [[ -f "$d/$stem.title.txt" ]] && title="$d/$stem.title.txt"

  if [[ "${GRADE_SKIP_CLAUDE:-0}" != "1" && -n "$tx" ]]; then
    local tmp; tmp="$(mktemp -d)"
    if python3 "$here/build_prompt.py" "$clip" "$tx" "${title:-/dev/null}" > "$tmp/prompt.txt" 2>/dev/null \
       && run_claude_step grade-clip "$tmp/prompt.txt" "$tmp/reply.txt" 2>"$tmp/err"; then
      python3 "$here/parse_reply.py" "$tmp/reply.txt" > "$tmp/claude.json" 2>/dev/null \
        && cjson="$d/.${stem}.grade.claude.json" && cp "$tmp/claude.json" "$cjson"
    else
      echo "grade-clip: claude rubric unavailable; proxy-only for $clip" >&2
    fi
    rm -rf "$tmp"
  fi

  local cargs=()
  [[ -n "$cjson" && -f "$cjson" ]] && cargs=(--claude-json "$cjson")

  if ! python3 "$here/grade.py" "$clip" "$out" "${skip[@]+"${skip[@]}"}" --scene "$scene" "${cargs[@]+"${cargs[@]}"}" >/dev/null 2>"$out.err"; then
    echo "grade-clip: grade.py failed; emitting DROSS for $clip" >&2
    cat "$out.err" >&2 || true
    printf '{"clip":"%s","grade":0,"tier":"DROSS","hard_caps":[],"signals":{},"fix_routes":[],"source":"%s"}' \
      "$clip" "$(basename "$(dirname "$clip")")" > "$out"
  fi
  rm -f "$out.err"
  printf '%s' "$sig" > "$meta"
  echo "$out"
}

if [[ "${1:-}" == "--backlog" ]]; then
  outdir="${2:-${OUTPUT_DIR:-output}}"
  outdir="${outdir%/}"
  [[ -d "$outdir" ]] || { echo "grade-clip: backlog dir not found: $outdir" >&2; exit 0; }
  export GRADE_SKIP_CLAUDE="${GRADE_SKIP_CLAUDE:-1}"   # backlog defaults proxy-only

  # collect clips: <outdir>/<src>/*.mp4 AND <outdir>/*.mp4, skipping _preview/source.
  # Read on FD 3 so a subprocess inside gradeone (ffmpeg/python) can never consume
  # the find stream off stdin and corrupt the path mid-loop.
  grades=()
  while IFS= read -r -u 3 mp4; do
    [[ -z "$mp4" ]] && continue
    case "$mp4" in
      */_preview/*|*/source/*|*/_toupload/*) continue;;
    esac
    g="$(gradeone "$mp4")" || continue
    grades+=("$g")
  done 3< <(find "$outdir" -type f -name '*.mp4' 2>/dev/null | sort)

  triage="$outdir/_triage.json"
  python3 - "$triage" "${grades[@]+"${grades[@]}"}" <<'PY'
import sys, json, datetime
out = sys.argv[1]
paths = sys.argv[2:]
gold, fixable, dross, by_source = [], [], [], {}
for p in paths:
    try:
        d = json.load(open(p))
    except Exception:
        continue
    clip = d.get("clip", p)
    src = d.get("source", "")
    by_source.setdefault(src, {"gold": 0, "fixable": 0, "dross": 0})
    tier = d.get("tier", "DROSS")
    if tier == "GOLD":
        gold.append(clip); by_source[src]["gold"] += 1
    elif tier == "FIXABLE":
        defect = (d.get("hard_caps") or ["?"])[0]
        fixable.append({"clip": clip, "defect": defect}); by_source[src]["fixable"] += 1
    else:
        reason = "rerun_recommended" if "rerun_recommended" in (d.get("fix_routes") or []) \
            else (",".join(d.get("hard_caps") or []) or "low_grade")
        dross.append({"clip": clip, "reason": reason}); by_source[src]["dross"] += 1
report = {
    "generated": datetime.datetime.now().isoformat(timespec="seconds"),
    "n": len(paths),
    "gold": gold, "fixable": fixable, "dross": dross, "by_source": by_source,
}
json.dump(report, open(out, "w"), indent=2)
print(json.dumps({"n": report["n"], "gold": len(gold),
                  "fixable": len(fixable), "dross": len(dross)}))
PY
  echo "grade-clip: backlog triage -> $triage" >&2
  exit 0
fi

if [[ -z "${1:-}" ]]; then
  echo "usage: grade-clip.sh <clip.mp4> | --backlog [output_dir]" >&2
  exit 2
fi

out="$(gradeone "$1")" || exit 0
[[ -f "$out" ]] && cat "$out"
exit 0
