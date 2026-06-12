#!/usr/bin/env bash
# scout-sources: deterministic source-video discovery via keyless yt-dlp.
# Searches seed niches, prefilters long-form candidates, fetches full metadata,
# and ranks by outlier score (views/day x views-per-sub x engagement x replay
# peakiness). No Claude, no API key.
set -uo pipefail

out="${1:-}"
shift 2>/dev/null || true

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
[[ -n "$out" ]] || out="$root/work/_scout/candidates.json"
mkdir -p "$(dirname "$out")"

per="${SCOUT_PER_QUERY:-12}"
shortlist="${SCOUT_SHORTLIST:-20}"
min_views="${SCOUT_MIN_VIEWS:-100000}"
dur_min="${SCOUT_DUR_MIN:-900}"     # 15 min
dur_max="${SCOUT_DUR_MAX:-10800}"   # 3 h

declare -a queries=()
if [[ $# -gt 0 ]]; then
  queries=("$@")
else
  while IFS= read -r q; do
    q="${q%%#*}"
    q="$(echo "$q" | xargs 2>/dev/null || true)"
    [[ -n "$q" ]] && queries+=("$q")
  done < "$here/niches.txt"
fi
[[ ${#queries[@]} -gt 0 ]] || { echo "scout-sources: no queries" >&2; exit 2; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/flat" "$tmp/full"

echo "scout-sources: searching ${#queries[@]} niche(s), $per results each" >&2
i=0
for q in "${queries[@]}"; do
  i=$((i + 1))
  yt-dlp "ytsearch${per}:${q}" --flat-playlist -J > "$tmp/flat/$i.json" 2>/dev/null &
done
wait

# merge + dedup + prefilter -> shortlist of ids by raw views
python3 - "$tmp/flat" "$shortlist" "$min_views" "$dur_min" "$dur_max" > "$tmp/ids.txt" <<'PY'
import glob, json, sys
d, shortlist, min_views, dur_min, dur_max = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
seen, cands = set(), []
for f in glob.glob(d + "/*.json"):
    try:
        entries = json.load(open(f)).get("entries") or []
    except ValueError:
        continue
    for e in entries:
        vid = e.get("id")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        views = e.get("view_count") or 0
        dur = e.get("duration") or 0
        if e.get("live_status") in ("is_live", "is_upcoming"):
            continue
        if views < min_views or not (dur_min <= dur <= dur_max):
            continue
        cands.append((views, vid))
cands.sort(reverse=True)
for _, vid in cands[:shortlist]:
    print(vid)
print(f"scout-sources: {len(cands)} prefiltered, fetching top {min(shortlist, len(cands))}", file=sys.stderr)
PY

[[ -s "$tmp/ids.txt" ]] || { echo "scout-sources: nothing survived the prefilter" >&2; exit 1; }

# full metadata per shortlisted candidate, 4-way parallel
xargs -P 4 -I{} sh -c \
  'yt-dlp -J --skip-download "https://www.youtube.com/watch?v={}" > "'"$tmp"'/full/{}.json" 2>/dev/null || true' \
  < "$tmp/ids.txt"

python3 "$here/score.py" "$tmp/full" "$out" "$root/work"
echo "$out"
