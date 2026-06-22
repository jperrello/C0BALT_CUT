#!/usr/bin/env bash
# sources-ledger: maintain work/sources.json — the registry of which source
# videos have been processed into shorts (title, url, produced shorts + grades,
# disk footprint, active|reaped status). Also mirrors a per-source bd memory so
# future sessions recall what's already been clipped. Pure scan, idempotent.
#   sources-ledger.sh sync         rebuild the whole registry from work/ + output/
#   sources-ledger.sh record <id>  upsert one source (pipeline end-of-run / reap)
#   sources-ledger.sh show         print the registry
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }
export WORK_DIR="$root/work"
export OUT_DIR="${OUTPUT_DIR:-$root/output}"

mode="${1:-sync}"
case "$mode" in
  sync)
    python3 "$here/ledger.py" sync
    ;;
  record)
    id="${2:-}"
    [[ -n "$id" ]] || { echo "usage: sources-ledger.sh record <id>" >&2; exit 2; }
    summary="$(python3 "$here/ledger.py" record "$id")" || exit 0
    [[ -n "$summary" ]] || exit 0
    echo "$summary"
    # best-effort per-source bd memory (keyed, so re-runs update in place)
    if command -v bd >/dev/null 2>&1; then
      msg="$(printf '%s' "$summary" | python3 -c 'import json,sys
d=json.load(sys.stdin)
g=d.get("top_grade"); g="n/a" if g is None else g
print("Shorted source \"%s\" (%s, slug %s): %s shorts, top grade %s, status %s. Re-ingest from %s" % (
  d.get("title"), d.get("id"), d.get("slug"), d.get("shorts_count"), g, d.get("status"), d.get("url")))')"
      [[ -n "$msg" ]] && bd remember "$msg" --key "source-${id}" >/dev/null 2>&1 || true
    fi
    ;;
  show)
    cat "$WORK_DIR/sources.json" 2>/dev/null || echo "[]"
    ;;
  *)
    echo "usage: sources-ledger.sh {sync|record <id>|show}" >&2
    exit 2
    ;;
esac
