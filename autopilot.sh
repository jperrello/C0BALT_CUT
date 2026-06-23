#!/usr/bin/env bash
# autopilot.sh — one tick of the autonomous shorts factory.
#   discover (scout) -> pick top unseen, non-HOLD candidate -> produce (start.sh:
#   ingest->edit->save->stage) -> notify. Learns from YouTube analytics first.
#
# Designed to be fired by launchd roughly hourly (see install-autopilot.sh).
# A mkdir lock serialises ticks so an "aggressive, multiple/day" schedule never
# stacks two pipeline runs on the same box: an idle tick scouts + produces one
# source; a tick that fires mid-run bails instantly at the lock.
#
#   autopilot.sh             # full tick (refresh analytics, scout, produce one source)
#   autopilot.sh --scout     # refresh + fresh scout + show the pick, but DON'T produce
#   autopilot.sh --dry-run    # refresh + pick from existing candidates, no scout, no produce
#   autopilot.sh --status     # print loop state (last run, lock, buffer, today's staged)
#
# Knobs (env or .env): AUTOPILOT_MIN_FREE_GB (25), AUTOPILOT_MAX_BUFFER_DAYS (30),
#   AUTOPILOT_SHORTS_N (-> SHORTS_N), AUTOPILOT_NOTIFY (1). start.sh knobs pass through.
set -uo pipefail

# launchd hands jobs a bare PATH — bake in where this Mac's tools actually live
# (claude in ~/.local/bin, yt-dlp/python3 in the python.org framework, ffmpeg/tmux
# in homebrew). install-autopilot.sh also sets PATH in the plist; belt + braces.
export PATH="$HOME/.local/bin:/Library/Frameworks/Python.framework/Versions/3.14/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

root="$(cd "$(dirname "$0")" && pwd)"
cd "$root" || exit 1
set -a; [ -f .env ] && . ./.env 2>/dev/null; set +a

state="$root/work/_autopilot"; mkdir -p "$state"
log="$state/autopilot.log"
say(){ printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$log" >&2; }

mode="run"
for a in "$@"; do case "$a" in
  --dry-run) mode="dry" ;;
  --scout)   mode="scout" ;;
  --status)  mode="status" ;;
  -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
  *) say "unknown arg: $a" ;;
esac; done

minfree="${AUTOPILOT_MIN_FREE_GB:-25}"
maxbuf="${AUTOPILOT_MAX_BUFFER_DAYS:-30}"
out="${OUTPUT_DIR:-output}"; [ -d "$out" ] || out="$root/output"

free_gb(){ df -g "$root" 2>/dev/null | awk 'NR==2{print $4}'; }
buffer_days(){ find "$out/_toupload" -maxdepth 1 -type d -name '20*-*-*' 2>/dev/null | wc -l | tr -d ' '; }

pick(){  # -> "url\ttitle\tverdict\tscore" of the best unseen non-HOLD candidate, or empty
  python3 - "$root" <<'PY'
import json, os, re, sys, hashlib
root = sys.argv[1]
def load(p, d):
    try: return json.load(open(p))
    except Exception: return d
cands = load(f"{root}/work/_scout/candidates.json", {}).get("candidates", [])
srcs = load(f"{root}/work/sources.json", [])
seen_urls = {s.get("url") for s in srcs if s.get("url")}
seen_ids = {s.get("id") for s in srcs if s.get("id")}
rs = []
sp = f"{root}/.claude/skills/schedule-drip/topics.scorelist"
if os.path.isfile(sp):
    for line in open(sp, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"): continue
        p = line.split(None, 1)
        if len(p) == 2: rs.append((p[0].upper(), p[1].lower()))
def verdict(hay):
    hay = hay.lower(); m = []
    for v, pat in rs:
        try: hit = re.search(pat, hay) is not None
        except re.error: hit = pat in hay
        if hit: m.append((v, pat))
    if any(v == "HOLD" for v, _ in m): return "HOLD"
    if any(v == "GO" for v, _ in m): return "GO"
    return "NEUTRAL"
def seen(c):
    url, cid = c.get("url", ""), c.get("id", "")
    if c.get("seen") or url in seen_urls or cid in seen_ids: return True
    h = hashlib.sha1(url.encode()).hexdigest()[:10]
    return os.path.isdir(f"{root}/work/{h}")
go, neutral = [], []
for c in cands:                      # candidates.json is already score-sorted by scout
    if seen(c): continue
    v = verdict(c.get("title", "") + " " + c.get("channel", ""))
    if v == "HOLD": continue
    (go if v == "GO" else neutral).append((c, v))
chosen = (go + neutral)[:1]           # proven-niche first, then neutral
if chosen:
    c, v = chosen[0]
    print(f'{c["url"]}\t{c.get("title","")}\t{v}\t{c.get("score","")}')
PY
}

today(){ date '+%Y-%m-%d'; }

notify(){  # $1 subtitle, $2 body
  [ "${AUTOPILOT_NOTIFY:-1}" = "1" ] || return 0
  command -v osascript >/dev/null 2>&1 || return 0
  osascript -e "display notification \"${2//\"/}\" with title \"C0BALT_CUT autopilot\" subtitle \"${1//\"/}\"" >/dev/null 2>&1 || true
}

staged_summary(){  # echo "<n> clips staged; today: <title> grade <g>"
  python3 - "$out" "$(today)" <<'PY'
import json, os, sys, glob
out, today = sys.argv[1], sys.argv[2]
sched = os.path.join(out, "_toupload", "schedule.json")
total = len(glob.glob(os.path.join(out, "_toupload", "20*-*-*", "*.mp4")))
line = f"{total} clip(s) staged"
try:
    d = json.load(open(sched)).get("days", {}).get(today, [])
    if d:
        c = d[0]
        line += f"; today: {os.path.basename(c.get('staged',''))} (grade {c.get('grade','?')}, {c.get('verdict','?')})"
    else:
        line += "; today: DARK"
except Exception:
    pass
print(line)
PY
}

# ---------------- status ----------------
if [ "$mode" = "status" ]; then
  echo "autopilot status @ $(date '+%F %T')"
  echo "  root:          $root"
  echo "  free disk:     $(free_gb) GB (floor ${minfree})"
  echo "  staged buffer: $(buffer_days) day(s) (ceiling ${maxbuf})"
  echo "  $(staged_summary)"
  if [ -d "$state/lock" ]; then
    echo "  lock:          HELD (pid $(cat "$state/lock/pid" 2>/dev/null || echo '?'))"
  else
    echo "  lock:          free"
  fi
  echo "  last analytics: $(cat "$state/analytics.csv.path" 2>/dev/null || echo none)"
  [ -f "$state/produced.log" ] && { echo "  last produced:"; tail -3 "$state/produced.log" | sed 's/^/    /'; }
  exit 0
fi

# ---------------- analytics refresh (idempotent; no-op on unchanged export) ----------------
bash "$root/.claude/skills/analytics-feedback/analytics-feedback.sh" 2>&1 | sed 's/^/  /' >>"$log" 2>&1 || say "analytics-feedback skipped"

# dry-run: just show the pick from EXISTING candidates, no lock, no scout, no produce
if [ "$mode" = "dry" ]; then
  sel="$(pick)"
  if [ -z "$sel" ]; then say "[dry] no unseen non-HOLD candidate in work/_scout/candidates.json"; exit 0; fi
  IFS=$'\t' read -r url title verd score <<<"$sel"
  say "[dry] would produce: $title"
  say "[dry]   url=$url verdict=$verd scout_score=$score"
  say "[dry]   $(staged_summary)"
  exit 0
fi

# ---------------- single-instance lock (mkdir is atomic) ----------------
lock="$state/lock"
if ! mkdir "$lock" 2>/dev/null; then
  pid="$(cat "$lock/pid" 2>/dev/null || echo '')"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    say "another tick is running (pid $pid); exiting"; exit 0
  fi
  say "stale lock (pid '${pid:-none}' gone); reclaiming"; rm -rf "$lock"; mkdir "$lock"
fi
echo $$ >"$lock/pid"
trap 'rm -rf "$lock"' EXIT INT TERM

# ---------------- disk gate ----------------
fg="$(free_gb)"
if [ -n "$fg" ] && [ "$fg" -lt "$minfree" ] 2>/dev/null; then
  say "disk low (${fg}GB < ${minfree}GB) — reaping reclaimable backlog"
  bash "$root/.claude/skills/reap-source/reap-source.sh" --backlog >/dev/null 2>&1 || true
  fg="$(free_gb)"
  if [ -n "$fg" ] && [ "$fg" -lt "$minfree" ] 2>/dev/null; then
    say "still low (${fg}GB) after reap — skipping production this tick"
    notify "disk low" "${fg}GB free (< ${minfree}); paused production"
    exit 0
  fi
fi

# ---------------- buffer backstop (aggressive mode: a high ceiling, not a brake) ----------------
bd="$(buffer_days)"
if [ -n "$bd" ] && [ "$bd" -ge "$maxbuf" ] 2>/dev/null; then
  say "staged buffer ${bd}d >= ${maxbuf}d ceiling — skipping production this tick"
  exit 0
fi

# ---------------- scout (fresh discovery) ----------------
say "scout-sources"
bash "$root/.claude/skills/scout-sources/scout-sources.sh" >>"$log" 2>&1 || { say "scout failed"; exit 0; }

# ---------------- pick ----------------
sel="$(pick)"
if [ -z "$sel" ]; then say "no unseen non-HOLD candidate — nothing to produce"; exit 0; fi
IFS=$'\t' read -r url title verd score <<<"$sel"

if [ "$mode" = "scout" ]; then
  say "[scout] top pick: $title"
  say "[scout]   url=$url verdict=$verd scout_score=$score (not producing — --scout)"
  exit 0
fi

# ---------------- produce ----------------
say "producing [$verd score=$score]: $title"
say "  url=$url"
[ -n "${AUTOPILOT_SHORTS_N:-}" ] && export SHORTS_N="$AUTOPILOT_SHORTS_N"
start_ts="$(date +%s)"
if bash "$root/start.sh" "$url" >>"$log" 2>&1; then
  dur=$(( $(date +%s) - start_ts ))
  sum="$(staged_summary)"
  say "DONE in ${dur}s — $sum"
  printf '[%s] OK %ss %s | %s | %s\n' "$(date '+%F %T')" "$dur" "$verd" "$title" "$url" >>"$state/produced.log"
  notify "$title" "$sum"
else
  say "start.sh FAILED for $url (see $log)"
  printf '[%s] FAIL %s | %s\n' "$(date '+%F %T')" "$title" "$url" >>"$state/produced.log"
  notify "produce failed" "$title"
  exit 1
fi
