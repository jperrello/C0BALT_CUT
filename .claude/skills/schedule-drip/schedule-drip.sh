#!/usr/bin/env bash
# schedule-drip: deterministic greedy scheduler over the graded clips. STAGING-
# HANDOFF ONLY — no auto-upload (no API key in the stack). Reads every
# output/**/*.grade.json + the checked-in topics.scorelist + an OPTIONAL
# output/upload-log.json, then stages a daily drip into output/_toupload/<date>/
# (clip copy + metadata.txt) plus a top-level schedule.json with the per-day plan,
# gap_warnings (the dark-gap alarm), and de-dupe/drop decisions.
#
# Gate: GOLD-first (tier==GOLD, or grade>=GRADE_MIN_UPLOAD) with NO unfixed
# hard_caps. Rank by grade desc, match source-slug+title against topics.scorelist
# (GO fills days first, HOLD only backfills a day that would otherwise be dark),
# de-dupe near-identical clips (same source + high title-token overlap), enforce
# MAX_PER_SOURCE_PER_DAY=1 round-robin (the 53-from-one-source feed-fatigue fix),
# fill POSTS_PER_DAY over DRIP_HORIZON_DAYS, drop anything already in upload-log.
#
# Usage: schedule-drip.sh [output_dir=output]
# Knobs: POSTS_PER_DAY (1), MAX_PER_SOURCE_PER_DAY (1), DRIP_HORIZON_DAYS (14),
#        GRADE_MIN_UPLOAD (60).
# NON-FATAL: any error -> exit 0 without staging. Idempotent: _toupload rebuilt
# deterministically each run.
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }

outdir="${1:-output}"
[[ "$outdir" = /* ]] || outdir="$root/$outdir"
scorelist="$here/topics.scorelist"
today="$(date +%F)"

if [[ ! -d "$outdir" ]]; then
  echo "schedule-drip: output dir not found: $outdir (passthrough)" >&2
  exit 0
fi

python3 "$here/schedule.py" "$root" "$outdir" "$scorelist" "$today" || {
  echo "schedule-drip: scheduler errored (non-fatal)" >&2
  exit 0
}
exit 0
