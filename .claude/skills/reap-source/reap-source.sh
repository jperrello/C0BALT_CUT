#!/usr/bin/env bash
# reap-source: reclaim disk by deleting a processed source's HEAVY artifacts —
# the full podcast source.mp4 (re-downloadable from its saved URL) + every
# clip_NN.* stage intermediate + the b-roll cutaway cache + the source's
# mcptube ingest. KEEPS all lightweight JSON (ingest/transcript/topics/segments/
# grade/broll_plan) as the on-disk memory, and updates work/sources.json.
# Manual only — never auto-runs. Refuses a source with no finished shorts in
# output/ unless --force.
#   reap-source.sh <id>            reap one source (e.g. 81d2d55a40)
#   reap-source.sh <id> --dry-run  show what would be freed, delete nothing
#   reap-source.sh --backlog       reap every source whose shorts are in output/
#   reap-source.sh --backlog -n    dry-run the whole sweep
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }
WORK="$root/work"
OUT="${OUTPUT_DIR:-$root/output}"
ledger="$(cd "$here/../sources-ledger" && pwd)/sources-ledger.sh"

dry=0; force=0; backlog=0; target=""
for a in "$@"; do
  case "$a" in
    --dry-run|-n) dry=1 ;;
    --force|-f)   force=1 ;;
    --backlog|--all) backlog=1 ;;
    -*) echo "reap-source: unknown flag $a" >&2; exit 2 ;;
    *)  target="$a" ;;
  esac
done

human() {
  python3 -c 'import sys
b=float(sys.argv[1])
for u in ("B","KB","MB","GB","TB"):
    if b<1024: print("%.1f%s"%(b,u)); break
    b/=1024
else: print("%.1fPB"%b)' "$1"
}

slug_of() {
  python3 -c 'import json,re,sys
try:
    d=json.load(open(sys.argv[1])); t=(d.get("title") or d.get("id") or d.get("source_id") or "").strip()
except Exception: t=""
print(re.sub(r"[^a-z0-9]+","-",t.lower()).strip("-")[:80])' "$1" 2>/dev/null
}

TALLY="$(mktemp)"; trap 'rm -f "$TALLY"' EXIT

# reap_one <id> -> echoes reclaimed bytes into $TALLY; human progress to stderr.
reap_one() {
  id="$1"; d="$WORK/$id"
  [[ -d "$d" ]] || { echo "  $id: no work dir, skip" >&2; return 1; }
  [[ -f "$d/ingest.json" ]] || { echo "  $id: no ingest.json (not a source), skip" >&2; return 1; }
  if [[ -f "$d/.reaped" && ! -f "$d/source.mp4" ]]; then
    echo "  $id: already reaped, skip" >&2; return 0
  fi

  # Never reap a source with a LIVE pipeline run — a tmux shorts-<id>-* pane or
  # any process referencing work/<id> means files are in flight and deleting
  # them would corrupt the run. Unconditional (even --force won't override).
  if tmux ls 2>/dev/null | grep -q "^shorts-${id}-" \
     || ps ax -o command 2>/dev/null | grep -F "work/$id" | grep -qv grep; then
    echo "  $id: ACTIVE pipeline run detected — skip (refusing to reap a live run)" >&2
    return 1
  fi

  slug="$(slug_of "$d/ingest.json")"; [[ -n "$slug" ]] || slug="$id"
  nshorts=0
  [[ -d "$OUT/$slug" ]] && nshorts="$(find "$OUT/$slug" -maxdepth 1 -name '*.mp4' ! -name '.*' ! -name '*.orig.mp4' 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$nshorts" -eq 0 && "$force" -ne 1 ]]; then
    echo "  $id ($slug): NO finished shorts in output/ — skip (use --force to reap anyway)" >&2
    return 1
  fi

  files="$(python3 "$here/plan.py" "$d")"
  bytes=0
  if [[ -n "$files" ]]; then
    bytes="$(printf '%s\n' "$files" | python3 -c 'import os,sys
t=0
for l in sys.stdin:
    p=l.strip()
    if not p: continue
    try: t+=os.path.getsize(p)
    except OSError: pass
print(t)')"
  fi

  label="$id ($slug, $nshorts shorts)"
  if [[ "$dry" -eq 1 ]]; then
    echo "  [dry-run] $label -> would free $(human "$bytes")" >&2
    echo "$bytes" >> "$TALLY"
    return 0
  fi

  # evict the source's b-roll from mcptube first (db/frames/chroma), then nuke files
  for plan in "$d"/clip_*.broll_plan.json; do
    [[ -f "$plan" ]] || continue
    bash "$(cd "$here/../broll-cleanup" && pwd)/broll-cleanup.sh" "$plan" >/dev/null 2>&1 || true
  done

  if [[ -n "$files" ]]; then
    printf '%s\n' "$files" | while IFS= read -r f; do [[ -n "$f" ]] && rm -f "$f"; done
  fi
  rmdir "$d/broll" 2>/dev/null || true

  printf '%s reaped %s\n' "$(date +%F)" "$bytes" > "$d/.reaped"
  bash "$ledger" record "$id" >/dev/null 2>&1 || true
  echo "  reaped $label -> freed $(human "$bytes")" >&2
  echo "$bytes" >> "$TALLY"
}

if [[ "$backlog" -eq 1 ]]; then
  [[ "$dry" -eq 1 ]] && echo "reap-source: DRY-RUN backlog sweep (nothing will be deleted)" >&2
  for d in "$WORK"/*/; do
    [[ -d "$d" ]] || continue
    id="$(basename "$d")"
    [[ -f "$d/ingest.json" ]] || continue
    reap_one "$id" || true
  done
elif [[ -n "$target" ]]; then
  target="${target#work/}"; target="${target%/}"
  reap_one "$target" || exit 1
else
  echo "usage: reap-source.sh <id> [--dry-run] [--force]   |   reap-source.sh --backlog [--dry-run]" >&2
  exit 2
fi

total="$(python3 -c 'import sys
print(sum(int(l) for l in open(sys.argv[1]) if l.strip()))' "$TALLY" 2>/dev/null || echo 0)"
verb="freed"; [[ "$dry" -eq 1 ]] && verb="would free"
echo "reap-source: $verb $(human "${total:-0}")" >&2
# keep the registry current after any real reap
[[ "$dry" -eq 1 ]] || bash "$ledger" sync >/dev/null 2>&1 || true
