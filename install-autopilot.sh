#!/usr/bin/env bash
# install-autopilot.sh — (un)install the launchd LaunchAgent that fires
# autopilot.sh every AUTOPILOT_INTERVAL seconds while the Mac is awake.
#
#   install-autopilot.sh                 # install + load (default 2h interval)
#   install-autopilot.sh --interval 5400 # install with a 90-min interval
#   install-autopilot.sh --now           # install, load, AND fire one tick immediately
#   install-autopilot.sh --status        # is the agent loaded? when does it next run?
#   install-autopilot.sh --uninstall     # unload + remove the agent
#
# launchd hands jobs a minimal PATH and coalesces ticks missed during sleep
# (one run on wake, not a backlog), which is exactly "run periodically whenever
# the Mac is on". The agent must be in the user's GUI session (it is, via
# gui/<uid>) so `claude -p` keeps its subscription auth. You must be LOGGED IN
# (past the FileVault/login screen) — powered-on-but-locked won't run it.
set -uo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
label="com.cobaltcut.autopilot"
uid="$(id -u)"
plist="$HOME/Library/LaunchAgents/${label}.plist"
# 1h ticks = "aggressive": when idle a tick scouts + produces one source; ticks
# that fire mid-run bail instantly at the lock, so the box runs back-to-back
# with minimal idle. Raise for a gentler cadence (--interval 10800 = 3h).
interval="${AUTOPILOT_INTERVAL:-3600}"
action="install"; runnow=0

while [ $# -gt 0 ]; do case "$1" in
  --interval) interval="$2"; shift 2 ;;
  --now)      runnow=1; shift ;;
  --uninstall|--remove) action="uninstall"; shift ;;
  --status)   action="status"; shift ;;
  -h|--help)  sed -n '2,16p' "$0"; exit 0 ;;
  *) echo "unknown arg: $1" >&2; exit 2 ;;
esac; done

boot_out(){ launchctl bootout "gui/$uid/$label" 2>/dev/null || launchctl unload "$plist" 2>/dev/null || true; }

if [ "$action" = "status" ]; then
  if launchctl print "gui/$uid/$label" >/dev/null 2>&1; then
    echo "loaded: $label"
    launchctl print "gui/$uid/$label" 2>/dev/null | grep -Ei "state|run interval|last exit|program =|/autopilot" | sed 's/^/  /'
  else
    echo "not loaded (run: bash install-autopilot.sh)"
  fi
  [ -f "$plist" ] && echo "plist: $plist"
  exit 0
fi

if [ "$action" = "uninstall" ]; then
  boot_out
  rm -f "$plist"
  echo "autopilot agent uninstalled ($label)"
  exit 0
fi

# ---- build a fat PATH from where THIS Mac's tools actually live ----
# direct colon-join with inline dedup (no word-splitting / awk / paste, so it
# behaves identically whether sourced under bash or zsh).
fatpath=""
add_path(){ case ":$fatpath:" in *":$1:"*) ;; *) fatpath="${fatpath:+$fatpath:}$1" ;; esac; }
for b in claude python3 yt-dlp ffmpeg ffprobe tmux; do
  p="$(command -v "$b" 2>/dev/null)" && add_path "$(dirname "$p")"
done
for d in /opt/homebrew/bin /usr/local/bin "$HOME/.local/bin" /usr/bin /bin /usr/sbin /sbin; do add_path "$d"; done

mkdir -p "$HOME/Library/LaunchAgents" "$root/work/_autopilot"

cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${root}/autopilot.sh</string>
  </array>
  <key>WorkingDirectory</key><string>${root}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>${fatpath}</string>
    <key>HOME</key><string>${HOME}</string>
  </dict>
  <key>StartInterval</key><integer>${interval}</integer>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Standard</string>
  <key>Nice</key><integer>5</integer>
  <key>StandardOutPath</key><string>${root}/work/_autopilot/launchd.out.log</string>
  <key>StandardErrorPath</key><string>${root}/work/_autopilot/launchd.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$plist" >/dev/null || { echo "ERROR: malformed plist at $plist" >&2; exit 1; }

boot_out
if launchctl bootstrap "gui/$uid" "$plist" 2>/dev/null || launchctl load "$plist" 2>/dev/null; then
  echo "autopilot agent loaded: $label"
  echo "  fires:    every ${interval}s (~$(awk "BEGIN{printf \"%.1f\", ${interval}/3600}")h) while logged in"
  echo "  script:   ${root}/autopilot.sh"
  echo "  logs:     ${root}/work/_autopilot/{autopilot,produced,launchd.*}.log"
  echo "  PATH:     ${fatpath}"
else
  echo "ERROR: launchctl failed to load $plist" >&2; exit 1
fi

if [ "$runnow" = "1" ]; then
  echo "kicking one tick now..."
  launchctl kickstart "gui/$uid/$label" 2>/dev/null || bash "$root/autopilot.sh" &
fi

echo
echo "next steps:"
echo "  bash install-autopilot.sh --status     # confirm it's scheduled"
echo "  bash autopilot.sh --scout              # dry produce-pick against a live scout"
echo "  tail -f work/_autopilot/autopilot.log  # watch ticks"
echo "  bash install-autopilot.sh --uninstall  # stop it"
