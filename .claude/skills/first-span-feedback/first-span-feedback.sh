#!/usr/bin/env bash
# first-span-feedback: the pre-fanout learning gate. start.sh finishes SPAN 0
# alone (through the normal edit/captions/completion chain), then this skill
# records a shot-scraper `video` demo of a generated per-span REVIEW PAGE, has a
# Claude reviewer WATCH it (via a contact sheet, like director-pass), and — when
# the reviewer names a SYSTEMIC defect that clears a hard three-gate re-verify —
# makes a permanent codebase change so every later span (and every future run)
# inherits the fix.
#
# PHASE 1 (this file): record -> review -> write verdict + .fsfmeta -> exit 0.
# There is NO fixer / git / commit yet — a flagged defect is surfaced only. The
# fix loop + three gates + commit-scope land in Phases 2-3.
#
# NON-FATAL everywhere: a missing shot-scraper, a record failure, a parse
# failure — all leave span 0 and the code untouched and exit 0, so fan-out
# proceeds on unchanged code. Idempotent via a .fsfmeta mtime signature.
#
#   first-span-feedback.sh <work_id> <clip_stem> <slug> <saved_mp4> [--pane <p>]
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }

frames_py="$here/../director-pass/frames.py"
NFR="${FSF_FRAMES:-12}"
PORT="${FSF_PORT:-8917}"

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
probe_dur() { ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 "$1" 2>/dev/null; }

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

dir="$root/work/$id"
if [[ ! -f "$saved" ]]; then
  echo "first-span-feedback: saved span-0 clip not found: $saved — skipping" >&2
  exit 0
fi

# grade.json: mirrored next to the saved clip, or the work-dir sidecar.
grade=""
for g in "${saved%.*}.grade.json" "$dir/$stem.grade.json"; do
  [[ -f "$g" ]] && { grade="$g"; break; }
done

# ---- guard: idempotency ----------------------------------------------------
sig="$(mtime "$saved")"
[[ -n "$grade" ]] && sig="$sig|$(mtime "$grade")"
sig="$sig|fsf=${FIRST_SPAN_FEEDBACK:-1}|v1"
meta="$dir/$stem.fsfmeta"
verdict_json="$dir/_preview/span0-feedback.json"
if [[ -f "$verdict_json" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "first-span-feedback: cache hit at $verdict_json" >&2
  exit 0
fi

# ---- probe: shot-scraper (uvx-isolated, decoupled from the vendored 1.60) --
# Off PATH / not provisionable -> degrade non-fatally: span 0 ships unmodified.
if ! command -v uvx >/dev/null 2>&1 || ! uvx shot-scraper --version >/dev/null 2>&1; then
  echo "first-span-feedback: uvx shot-scraper unavailable — skipping demo/review" >&2
  exit 0
fi

preview="$dir/_preview"
mkdir -p "$preview"

# ---- record_demo -----------------------------------------------------------
# Build the review page + storyboard, serve it over a throwaway http.server, and
# record the page playing span 0 through once. Any failure here is non-fatal;
# review falls back to the raw clip so the loop still runs.
dur="$(probe_dur "$saved")"; [[ -z "$dur" ]] && dur="30"
page="$preview/span0-review.html"
storyboard="$preview/storyboard.yml"
demo="$preview/span0-demo.mp4"

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

# ---- review ----------------------------------------------------------------
# Watch the recorded demo (or, if the record degraded, the raw clip) via ONE
# labelled contact sheet, exactly as director-pass does.
review_src="$saved"
[[ -s "$demo" ]] && review_src="$demo"

tx=""
for f in "$dir/$stem.tight.transcript.json" "$dir/$stem.transcript.json"; do
  [[ -f "$f" ]] && { tx="$f"; break; }
done

sheetdir="$preview/review"
mkdir -p "$sheetdir"
sheetjson="$(python3 "$frames_py" "$review_src" "$sheetdir" --n "$NFR" 2>/dev/null)"
sheet="$(printf '%s' "$sheetjson" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("sheet",""))
except Exception: print("")' 2>/dev/null)"

reply="$sheetdir/reply.txt"
if [[ -z "$sheet" || ! -f "$sheet" ]]; then
  echo "first-span-feedback: contact sheet build failed — surfacing clean verdict" >&2
  printf '{"defect":false}' > "$reply"
else
  printf '%s' "$sheetjson" > "$sheetdir/frames.json"
  python3 "$here/build_prompt.py" "$sheet" "$sheetdir/frames.json" \
    --grade "${grade:-}" --transcript "$tx" --dur "$dur" > "$sheetdir/prompt.txt" 2>/dev/null \
    || echo "first-span-feedback: prompt build failed" >&2

  # FSF_REPLY_FILE is the test seam (mirrors director-pass's DIRECTOR_REPLY_FILE):
  # a canned verdict stands in for the live reviewer for offline proofs.
  if [[ -n "${FSF_REPLY_FILE:-}" && -f "$FSF_REPLY_FILE" ]]; then
    cp "$FSF_REPLY_FILE" "$reply"
  elif [[ ! -f "$sheetdir/prompt.txt" ]] || ! run_claude_step first-span-review "$sheetdir/prompt.txt" "$reply" 2>"$sheetdir/err"; then
    echo "first-span-feedback: reviewer unavailable — surfacing clean verdict" >&2
    printf '{"defect":false}' > "$reply"
  fi
fi

# ---- verdict + persist -----------------------------------------------------
raw_verdict="$(python3 "$here/parse_reply.py" "$reply" 2>/dev/null)"
[[ -z "$raw_verdict" ]] && raw_verdict='{"defect": false}'

FSF_RAW_VERDICT="$raw_verdict" python3 - "$verdict_json" "$saved" "$review_src" "$id" "$stem" "$demo" <<'PY'
import json, sys, os
out, saved, review_src, wid, stem, demo = sys.argv[1:7]
try:
    v = json.loads(os.environ.get("FSF_RAW_VERDICT", ""))
except Exception:
    v = {"defect": False}
doc = {
    "work_id": wid, "clip_stem": stem,
    "clip": saved,
    "demo": demo if os.path.isfile(demo) else "",
    "reviewed": review_src,
    "verdict": v,
    "action": "fix_pending" if v.get("defect") else "clean",
    "phase": 1,
}
json.dump(doc, open(out, "w"), indent=2)
sys.stderr.write(json.dumps({"defect": bool(v.get("defect")), "action": doc["action"]}) + "\n")
PY

printf '%s' "$sig" > "$meta"

if python3 -c 'import json,sys;sys.exit(0 if json.load(open(sys.argv[1]))["verdict"].get("defect") else 1)' "$verdict_json" 2>/dev/null; then
  echo "first-span-feedback: SYSTEMIC defect flagged (surfaced-only in phase 1) -> $verdict_json" >&2
else
  echo "first-span-feedback: span 0 clean -> $verdict_json" >&2
fi
exit 0
