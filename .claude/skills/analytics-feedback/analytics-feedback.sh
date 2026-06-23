#!/usr/bin/env bash
# analytics-feedback: learn GO/HOLD topic verdicts from the newest YouTube Studio
# CSV export and rewrite the managed blocks of topics.scorelist + niches.txt.
# Idempotent: no-op unless the export's mtime changed (or --force). No Claude.
#   analytics-feedback.sh                 # newest export under ~/Downloads/Content*<channel>*/
#   analytics-feedback.sh /path/Table\ data.csv
#   analytics-feedback.sh --force         # re-learn from the newest export even if unchanged
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"

force=0
csv=""
for a in "$@"; do
  case "$a" in
    --force) force=1 ;;
    *) csv="$a" ;;
  esac
done

dir="${AUTOPILOT_ANALYTICS_DIR:-$HOME/Downloads}"
name="${AUTOPILOT_ANALYTICS_NAME:-Table data.csv}"
chan="${AUTOPILOT_ANALYTICS_CHANNEL:-C0BALT_CUT}"

if [[ -z "$csv" ]]; then
  csv="$(find "$dir" -maxdepth 2 -type f -name "$name" -path "*${chan}*" -print0 2>/dev/null \
         | xargs -0 ls -t 2>/dev/null | head -1)"
fi
[[ -n "$csv" && -f "$csv" ]] || { echo "analytics-feedback: no '$name' under $dir/*${chan}* — skipping" >&2; exit 0; }

state="$root/work/_autopilot"; mkdir -p "$state"
stamp="$(stat -f %m "$csv" 2>/dev/null || echo 0)"
last="$(cat "$state/analytics.csv.mtime" 2>/dev/null || echo 0)"
if [[ "$force" -eq 0 && "$stamp" == "$last" && "$stamp" != "0" ]]; then
  echo "analytics-feedback: $(basename "$(dirname "$csv")") unchanged since last run — no-op" >&2
  exit 0
fi

scorelist="$root/.claude/skills/schedule-drip/topics.scorelist"
niches="$root/.claude/skills/scout-sources/niches.txt"
scores="$state/topic_scores.json"

python3 "$here/feedback.py" "$csv" "$scorelist" "$niches" "$scores" || {
  echo "analytics-feedback: feedback.py failed (leaving scorelist/niches untouched)" >&2; exit 1; }

printf '%s' "$stamp" > "$state/analytics.csv.mtime"
printf '%s\n' "$csv" > "$state/analytics.csv.path"
echo "analytics-feedback: learned from $csv" >&2
