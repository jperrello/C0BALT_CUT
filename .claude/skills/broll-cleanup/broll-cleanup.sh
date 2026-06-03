#!/usr/bin/env bash
# broll-cleanup: deferred end-of-run eviction. For ONLY the b-roll source
# video_ids this run ingested (broll_plan.json ingested_video_ids), evict from
# mcptube AND delete the local work/<id>/broll/*.mp4 cache. Never touches the
# podcast source or broll_plan.json (placement metadata persists for editors).
set -uo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: broll-cleanup.sh <broll_plan.json> [<broll_plan.json> ...]" >&2
  exit 2
fi

MT="${MCPTUBE_BIN:-$HOME/.local/pipx/venvs/mcptube/bin/mcptube}"

# union ingested ids across all plans (bash 3.2 — no associative arrays)
seen=" "
nseen=0
removed=0
for plan in "$@"; do
  [[ -f "$plan" ]] || { echo "broll-cleanup: skip missing $plan" >&2; continue; }
  while IFS= read -r vid; do
    [[ -z "$vid" ]] && continue
    case "$seen" in *" $vid "*) continue;; esac
    seen="$seen$vid "
    nseen=$((nseen+1))
    if [[ -x "$MT" ]]; then
      if "$MT" remove "$vid" >/dev/null 2>&1; then
        removed=$((removed+1)); echo "broll-cleanup: mcptube removed $vid" >&2
      else
        echo "broll-cleanup: mcptube remove $vid failed (already gone?)" >&2
      fi
    fi
  done < <(python3 -c 'import json,sys
try:
    print("\n".join(json.load(open(sys.argv[1])).get("ingested_video_ids",[])))
except Exception: pass' "$plan")

  # delete local broll cache: every clip_path file + the broll dir mp4s
  while IFS= read -r f; do
    [[ -f "$f" ]] && { rm -f "$f"; echo "broll-cleanup: deleted $f" >&2; }
  done < <(python3 -c 'import json,sys
try:
    for p in json.load(open(sys.argv[1])).get("picks",[]):
        cp=p.get("clip_path")
        if cp: print(cp)
except Exception: pass' "$plan")

  # also clear any stragglers in the broll dir derived from the first clip_path
  brdir="$(python3 -c 'import json,sys,os
try:
    ps=json.load(open(sys.argv[1])).get("picks",[])
    if ps and ps[0].get("clip_path"): print(os.path.dirname(ps[0]["clip_path"]))
except Exception: pass' "$plan")"
  if [[ -n "$brdir" && -d "$brdir" && "$(basename "$brdir")" == "broll" ]]; then
    # match every cached cutaway, not just *.mp4: yt-dlp merges often land as
    # <slot>.mp4.webm / .mkv, so a bare *.mp4 glob leaks the real files.
    rm -f "$brdir"/*broll_* 2>/dev/null || true
    rmdir "$brdir" 2>/dev/null || true
  fi
done

echo "broll-cleanup: done (mcptube entries removed=$removed, ids=$nseen)" >&2
