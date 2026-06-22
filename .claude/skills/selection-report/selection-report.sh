#!/usr/bin/env bash
# selection-report: write output/<slug>/_selection.json for a source (shipped
# shorts + the considered-not-shipped RLM candidate menu + topics). Deterministic,
# no Claude, idempotent, non-fatal. shorts-aun.
#
#   selection-report.sh <work_dir> [output_root]      # one source
#   selection-report.sh --backlog [output_root]       # every work/ with output
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."
if [[ -f "$root/.env" ]]; then set -a; . "$root/.env"; set +a; fi

slug_of() {  # work_dir -> output slug (matches start.sh / report.py)
  python3 -c 'import json,sys,re
try:
    d=json.load(open(sys.argv[1]+"/ingest.json")); t=(d.get("title") or d.get("id") or "").strip()
except Exception: t=""
import os
print(re.sub(r"[^a-z0-9]+","-",t.lower()).strip("-")[:80] or os.path.basename(sys.argv[1].rstrip("/")))' "$1" 2>/dev/null
}

if [[ "${1:-}" == "--backlog" ]]; then
  out_root="${2:-${OUTPUT_DIR:-$root/output}}"
  n=0
  for wd in "$root"/work/*/; do
    [[ -f "$wd/ingest.json" ]] || continue
    slug="$(slug_of "$wd")"
    [[ -n "$slug" && -d "$out_root/$slug" ]] || continue
    if python3 "$here/report.py" "$wd" "$out_root" >/dev/null 2>&1; then
      echo "selection-report: $slug" >&2
      n=$((n + 1))
    fi
  done
  echo "selection-report: backfilled $n source(s)" >&2
  exit 0
fi

work_dir="${1:-}"
out_root="${2:-${OUTPUT_DIR:-$root/output}}"
if [[ -z "$work_dir" || ! -d "$work_dir" ]]; then
  echo "usage: selection-report.sh <work_dir> [output_root] | --backlog [output_root]" >&2
  exit 2
fi
python3 "$here/report.py" "$work_dir" "$out_root"
