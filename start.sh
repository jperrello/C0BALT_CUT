#!/usr/bin/env bash
# /start orchestrator. Fans the shorts pipeline across long-lived tmux panes.
#
# Architecture
# ------------
# The orchestrator (this script) is the single driver. Bash/media panes run a
# plain shell. Semantic lanes run long-lived Claude sessions so related steps
# can keep artifact context warm within one source/span.
#
# For Claude-driven skills, we pass `--pane <name>` and set
# SHORTS_PANE_MODE=chat. The skill wrapper writes the prompt to disk, sends a
# small file-based task into that pane, waits for out.txt to settle, then parses
# the reply. This avoids a fresh Claude process per semantic step.
#
# For bash steps, the orchestrator just runs them directly (no pane round-trip
# is needed — bash is already fast).
#
# Context rule:
# Clear at lane boundaries, keep context within the lane. The analysis pane
# handles one source transcript. Span work runs in a fixed pool of max_par
# lanes; each lane owns ONE long-lived Claude pane reused across spans and
# phases, with /clear between dispatches so context never leaks across spans
# (and so a 77-span run holds max_par claude processes, not 70+).

set -uo pipefail

# This orchestrator may be invoked from inside a Claude Code session; child
# `claude -p` invocations (in panes or fallback) refuse to nest unless these
# are unset. Strip them at the very top so every child inherits a clean env.
unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT

# Timing instrument: `timed <label> <kind> -- <cmd>` brackets each skill call
# and appends one JSONL record to $SHORTS_TIMING_LOG (set once `dir` is known
# below). pane.sh sources the same lib for its claude sub-records, and the
# end-of-run tail folds the log into run_timing.json + _timing.html. No-op when
# the log is unset, so sourcing here is free.
source "$(cd "$(dirname "$0")" && pwd)/.claude/skills/_lib/timing.sh"
# Encoder probe (_shorts_encoder) so the lane/thread budget below can be
# encoder-aware — VideoToolbox lanes share the fixed HW encoder, x264 lanes
# genuinely compete for cores.
source "$(cd "$(dirname "$0")" && pwd)/.claude/skills/_lib/encode.sh"
# Overlay compositor (compose_overlays) — fuses each overlay cluster's
# OVERLAY_PLAN_ONLY specs into ONE ffmpeg pass (the 6-encode -> 2-encode lever).
source "$(cd "$(dirname "$0")" && pwd)/.claude/skills/_lib/overlay.sh"

n="${SHORTS_N:-5}"
dmin="${SHORTS_DMIN:-28}"
dmax="${SHORTS_DMAX:-55}"

# Core budget: leave one logical CPU free so the machine stays usable. The
# lane count (max_par) and the per-lane encode budget (SHORTS_THREADS) are
# resolved AFTER pick-segments sets `count` (the span count doesn't exist yet
# here), so the multi-lane default can be capped to the actual work. Whisper is
# phase-1 and serial — nothing else runs alongside it — so it gets the whole
# budget now.
ncpu="$(sysctl -n hw.logicalcpu 2>/dev/null || echo 8)"
budget=$(( ncpu - 1 )); (( budget < 1 )) && budget=1
export SHORTS_WHISPER_THREADS="${SHORTS_WHISPER_THREADS:-$budget}"

if [[ $# -lt 1 ]]; then
  cat >&2 <<EOF
usage: start.sh <url-or-source-id> [<url-or-source-id> ...]

Pass multiple URLs / video IDs / source-ids to process them sequentially.
Each video's tmux panes are torn down before the next one starts.
After a successful run on a YouTube ID, edited_at is stamped in mcptube.

env knobs:
  SHORTS_N        number of spans to pick (default 5)
  SHORTS_DMIN     min span seconds (default 28)
  SHORTS_DMAX     max span seconds (SELECTION budget, default 55 — pick generously; downstream trim-filler/tighten-pace land the DELIVERED short in the ~30-40s sweet spot)
  MCPTUBE_URL     mcptube MCP endpoint (default http://127.0.0.1:9093/mcp)
  MCPTUBE_DB      mcptube sqlite path (default \$HOME/.mcptube/mcptube.db)
EOF
  exit 2
fi

# ---- multi-arg wrapper ---------------------------------------------------
# Re-exec self once per arg so each video gets a clean trap/pane lifecycle.
if [[ $# -gt 1 || "$1" =~ [[:space:]] ]]; then
  self="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  db="${MCPTUBE_DB:-$HOME/.mcptube/mcptube.db}"
  declare -a batch=()
  if [[ $# -gt 1 ]]; then
    batch=("$@")
  else
    read -r -a batch <<< "$1"
  fi
  ok=0; fail=0; i=0; total="${#batch[@]}"
  for a in "${batch[@]}"; do
    [[ -n "$a" ]] || continue
    i=$((i + 1))
    echo
    echo "########## [$i/$total] $a ##########" >&2
    if bash "$self" "$a"; then
      ok=$((ok + 1))
      # If $a looks like a bare YouTube video_id (11 chars, [-_A-Za-z0-9]),
      # stamp edited_at. URLs handled by extracting the id below.
      vid=""
      if [[ "$a" =~ ^[A-Za-z0-9_-]{11}$ ]]; then
        vid="$a"
      elif [[ "$a" =~ (youtu\.be/|v=)([A-Za-z0-9_-]{11}) ]]; then
        vid="${BASH_REMATCH[2]}"
      fi
      if [[ -n "$vid" && -f "$db" ]]; then
        ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        sqlite3 "$db" "UPDATE videos SET edited_at = '$ts' WHERE video_id = '$vid';" \
          && echo "start: stamped edited_at for $vid" >&2
      fi
    else
      fail=$((fail + 1))
      echo "start: [$i/$total] $a FAILED — continuing" >&2
    fi
  done
  echo
  echo "start: batch done — $ok ok, $fail failed" >&2
  exit 0
fi

arg="$1"

root="$(cd "$(dirname "$0")" && pwd)"
cd "$root"
skill() { echo "$root/.claude/skills/$1/$1.sh"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

# Cluster-level idempotency signature for a fused compose pass: base mtime |
# quality | each spec's mtime. Same idiom as the per-skill .*meta — a re-run
# with an unchanged base + specs skips the fused encode.
_mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || echo 0; }
_cmpsig() {
  local base="$1" q="$2"; shift 2
  local sig; sig="$(_mtime "$base")|$q"
  local s
  for s in "$@"; do sig="$sig|$(_mtime "$s")"; done
  printf '%s' "$sig"
}

# Serial fallback for the captions overlay cluster: if the fused compose pass
# fails, fall back to the original burn-subtitles -> title-transition ->
# brand-overlays serial encodes (each skill's standalone apply path), so a
# compositor edge case never strands a span. Returns the final `marked` clip.
_overlay_serial_captions() {
  local idx="$1" base="$2" chunks="$3" title="$4" ingest="$5" marked="$6"
  local sub="$dir/clip_${idx}.sub.mp4"
  local titled="$dir/clip_${idx}.titled.mp4"
  bash "$(skill burn-subtitles)" "$base" "$chunks" "$sub" chunks >/dev/null || return 1
  bash "$(skill title-transition)" "$sub" "$title" "$titled" >/dev/null || return 1
  if ! bash "$(skill brand-overlays)" "$titled" "$ingest" "$marked" >/dev/null; then
    local credited="$dir/clip_${idx}.credited.mp4"
    bash "$(skill source-credit)" "$titled" "$ingest" "$credited" >/dev/null || cp "$titled" "$credited"
    bash "$(skill watermark)" "$credited" "$marked" >/dev/null || cp "$credited" "$marked"
  fi
  return 0
}

# Serial fallback for the completion overlay cluster: like-subscribe-overlay ->
# end-card (each skill's standalone apply path). bg-music already ran (audio
# bed, video copy) before this, so it is not part of the fallback.
_overlay_serial_completion() {
  local idx="$1" base="$2" out="$3"
  local ctaed="$dir/clip_${idx}.ctaed.mp4"
  bash "$(skill like-subscribe-overlay)" "$base" "$ctaed" 4.0 >/dev/null || cp "$base" "$ctaed"
  bash "$(skill end-card)" "$ctaed" "$out" >/dev/null || cp "$ctaed" "$out"
  return 0
}

youtube() {
  local val="$1"
  if [[ "$val" =~ ^[A-Za-z0-9_-]{11}$ ]]; then
    printf 'https://www.youtube.com/watch?v=%s\n' "$val"
    return 0
  fi
  printf '%s\n' "$val"
}

# ---- preflight: mcptube ---------------------------------------------------
mcp_url="${MCPTUBE_URL:-http://127.0.0.1:9093/mcp}"
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 4 "$mcp_url" 2>/dev/null)"
[[ -z "$code" || "$code" == "000" ]] && code="000"
case "$code" in
  200|204|406) log "preflight: mcptube ok ($code) at $mcp_url" ;;
  *)
    cat >&2 <<EOF
start: mcptube MCP server unreachable at $mcp_url (got HTTP $code).
       Start it with: mcptube serve
       Or override with MCPTUBE_URL=...
EOF
    exit 1
    ;;
esac

# ---- resolve source-id vs URL --------------------------------------------
# accept both a bare source-id and the documented work/<id> path form
arg="${arg#work/}"; arg="${arg%/}"
if [[ -d "work/$arg" && -f "work/$arg/source.mp4" ]]; then
  id="$arg"
  url=""
  log "reusing source-id $id"
else
  url="$(youtube "$arg")"
  id="$(printf '%s' "$url" | shasum | cut -c1-10)"
  log "new url $url -> source-id $id"
fi
dir="$root/work/$id"
mkdir -p "$dir/_pane"
export SHORTS_PANE_DIR="$dir/_pane"
export SHORTS_PANE_MODE=chat
# Timing log for this run. `timed` (start.sh wrappers) + pane.sh's claude
# sub-records append here; timing-report.py reduces it in the end-of-run tail.
export SHORTS_TIMING_LOG="$dir/run_timing.jsonl"
: > "$SHORTS_TIMING_LOG"

# ---- pane management ------------------------------------------------------
declare -a PANES=()

pane_new() {
  local name="$1"
  local mode="${2:-bash}"
  tmux kill-session -t "$name" 2>/dev/null
  tmux new-session -d -s "$name" -x 200 -y 50 "bash -l" 2>/dev/null
  mkdir -p "$SHORTS_PANE_DIR/$name"
  tmux set-option -t "$name" remain-on-exit on >/dev/null 2>&1 || true
  if [[ "$mode" == "claude" ]]; then
    tmux respawn-pane -k -t "$name" \
      "unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT; exec claude --dangerously-skip-permissions"
    pane_wait_idle "$name" 30 || log "warn: $name did not show a Claude prompt before dispatch"
    # No /clear here: a fresh session has nothing to clear, and racing a
    # slash command against the still-initializing TUI leaves "/clear"
    # unsubmitted in the input box — the next task paste then concatenates
    # onto it and gets swallowed as slash-command arguments.
  fi
  PANES+=("$name")
}

pane_wait_idle() {
  local pane="$1" timeout="${2:-10}"
  local waited=0
  while (( waited < timeout * 5 )); do
    if tmux capture-pane -t "$pane" -p -J -S -8 2>/dev/null | grep -qE '│ >|❯'; then
      return 0
    fi
    sleep 0.2
    waited=$((waited + 1))
  done
  return 1
}

pane_chat_clear() {
  local pane="$1"
  # Same paste-pause-Enter dance as run_claude_step: an Enter fired right
  # after a literal send races the TUI's paste handling and "/clear" sits
  # unsubmitted, poisoning the next dispatch.
  tmux send-keys -t "$pane" -l -- "/clear"
  sleep 1
  tmux send-keys -t "$pane" Enter
  sleep 0.5
  tmux send-keys -t "$pane" Enter
  pane_wait_idle "$pane" 10 || true
}

_cleaned=0
cleanup() {
  (( _cleaned )) && return 0
  _cleaned=1
  # Kill by name pattern, not the PANES array: per-span panes are created
  # inside background subshells (run_span/run_phase3/run_phase4), so their
  # pane_new appends never reach this parent's PANES copy. Globbing every
  # shorts-<id>-* session catches those leaked panes too.
  local killed=0 p
  for p in $(tmux ls -F '#{session_name}' 2>/dev/null | grep "^shorts-${id}-" || true); do
    tmux kill-session -t "$p" 2>/dev/null && killed=$((killed + 1))
  done
  log "cleanup: tore down $killed pane(s)"
  [[ -n "${UNBLOCKER_PID:-}" ]] && kill "$UNBLOCKER_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

# Watchdog: --dangerously-skip-permissions does NOT cover new-file Write
# prompts. Poll all session panes and auto-press "2" on any 1/2/3 menu.
unblocker_start() {
  [[ -n "${UNBLOCKER_PID:-}" ]] && return 0
  local log_file="${SHORTS_PANE_DIR}/unblocker.log"
  (
    while true; do
      while IFS= read -r s; do
        [[ -z "$s" ]] && continue
        if tmux capture-pane -t "$s" -p -S -20 2>/dev/null | grep -q "Yes, allow all edits during this session"; then
          tmux send-keys -t "$s" "2" Enter
          echo "[$(date +%H:%M:%S)] unblocked $s" >> "$log_file"
        fi
      done < <(tmux ls -F '#{session_name}' 2>/dev/null | grep "^shorts-${id}-" || true)
      sleep 5
    done
  ) >/dev/null 2>&1 &
  UNBLOCKER_PID=$!
  log "unblocker watchdog started (pid $UNBLOCKER_PID)"
}
unblocker_start

# pane_bash <pane> <step> <bash command line>
# Runs a bash command inside the pane; waits for completion via sentinel.
pane_bash() {
  local pane="$1" step="$2" cmd="$3"
  local sdir="$SHORTS_PANE_DIR/$pane/$step"
  mkdir -p "$sdir"
  rm -f "$sdir/done" "$sdir/exit"
  printf '%s\n' "$cmd" > "$sdir/cmd.sh"
  local launcher="bash '$sdir/cmd.sh' >>'$sdir/log' 2>&1 ; ec=\$? ; sync ; echo \$ec > '$sdir/exit' ; touch '$sdir/done'"
  tmux send-keys -t "$pane" "$launcher" Enter
}

# pane_wait <pane> <step> [timeout]
pane_wait() {
  local pane="$1" step="$2" timeout="${3:-3600}"
  local f="$SHORTS_PANE_DIR/$pane/$step/done"
  local waited=0
  while [[ ! -f "$f" ]]; do
    sleep 2
    waited=$((waited + 2))
    if (( waited >= timeout )); then
      log "pane_wait: timeout ${timeout}s waiting on $pane/$step"
      return 124
    fi
  done
  local ec=0
  [[ -f "$SHORTS_PANE_DIR/$pane/$step/exit" ]] && ec="$(cat "$SHORTS_PANE_DIR/$pane/$step/exit")"
  return "$ec"
}

# ---- phase 1: source-prep + analysis (parallel) --------------------------
sp="shorts-$id-srcprep"
an="shorts-$id-analysis"
mc="shorts-$id-mcptube"
log "[phase 1] launching $sp"
pane_new "$sp"

src="$dir/source.mp4"
tx="$dir/transcript.json"
ingest_json="$dir/ingest.json"
topics="$dir/topics.json"
thesis="$dir/thesis.json"
seg_raw="$dir/segments.raw.json"
seg_coh="$dir/segments.coherent.json"
seg_final="$dir/segments.json"

# srcprep — bash ingest + transcribe (skip if cached)
if [[ -f "$src" && -f "$tx" ]]; then
  log "[phase 1] srcprep cached (source.mp4 + transcript.json present)"
  mkdir -p "$SHORTS_PANE_DIR/$sp/srcprep"
  echo 0 > "$SHORTS_PANE_DIR/$sp/srcprep/exit"
  touch "$SHORTS_PANE_DIR/$sp/srcprep/done"
else
  if [[ -n "$url" ]]; then
    pane_bash "$sp" "srcprep" \
      "bash '$(skill ingest)' '$url' '$id' >/dev/null && bash '$(skill transcribe)' '$src' '$tx'"
  else
    pane_bash "$sp" "srcprep" \
      "bash '$(skill transcribe)' '$src' '$tx'"
  fi
fi

# analysis: mcptube add (if URL) — fire-and-poll from a shell pane. The
# analysis pane becomes a long-lived Claude lane after srcprep completes.
if [[ -n "$url" ]]; then
  log "[phase 1] analysis: mcptube add (background)"
  pane_new "$mc"
  pane_bash "$mc" "mcptube_add" \
    "claude -p --output-format text >/dev/null 2>&1 <<EOF
Call the mcptube MCP tool add_video with url=\"$url\". After it returns, reply with the single word 'done' and nothing else.
EOF"
fi

# Wait for srcprep (transcribe must finish before topics/picks/coherence)
log "[phase 1] waiting on srcprep..."
if ! pane_wait "$sp" "srcprep" 7200; then
  log "FATAL: srcprep failed; see $SHORTS_PANE_DIR/$sp/srcprep/log"
  exit 2
fi
log "[phase 1] srcprep done"

# Switch analysis into a persistent Claude lane. Keep this lane warm across
# source-level semantic steps; clear it before a new source, not between
# segment-topics / pick-segments / verify-coherence.
pane_new "$an" claude

# Run topics/picks/coherence through the analysis pane via --pane.
export SHORTS_TL_PHASE=analysis
log "[phase 1 / analysis] segment-topics"
timed segment-topics claude -- bash "$(skill segment-topics)" "$tx" "$topics" --pane "$an" || { log "FATAL: segment-topics"; exit 3; }
log "[phase 1 / analysis] derive-thesis"
timed derive-thesis claude -- bash "$(skill derive-thesis)" "$tx" "$topics" "$thesis" --pane "$an" || log "WARN: derive-thesis failed (non-fatal; picking theme-blind)"
log "[phase 1 / analysis] pick-segments"
timed pick-segments claude -- bash "$(skill pick-segments)" "$tx" "$seg_raw" "$n" "$dmin" "$dmax" "$topics" --pane "$an" || { log "FATAL: pick-segments"; exit 3; }
log "[phase 1 / analysis] verify-coherence"
timed verify-coherence claude -- bash "$(skill verify-coherence)" "$seg_raw" "$tx" "$seg_coh" "$dmin" --pane "$an" || { log "FATAL: verify-coherence"; exit 3; }
unset SHORTS_TL_PHASE

# bookend-trim was moved to phase 2 per spec; coherent spans become segments.json
# directly as the per-span input. Each editor pane will re-snap its own span.
if [[ ! -f "$seg_final" || "$seg_coh" -nt "$seg_final" ]]; then
  cp "$seg_coh" "$seg_final"
fi

# Every short uses the single channel title animation (glitch) — there is no
# per-span style pick anymore.
count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["shorts"]))' "$seg_final")"
log "[phase 1] $count span(s) survived coherence check"
[[ "$count" -gt 0 ]] || { log "FATAL: no spans survived"; exit 4; }

# ---- lane + encode budget (resolved now that `count` exists) --------------
# max_par: explicit SHORTS_MAX_PAR wins; otherwise a single-span run stays
# serial and a multi-span run defaults to 2 overlapping lanes (capped to the
# work and the core budget).
if [[ -n "${SHORTS_MAX_PAR:-}" ]]; then
  max_par="$SHORTS_MAX_PAR"
elif (( count <= 1 )); then
  max_par=1
else
  max_par=2
  (( max_par > count )) && max_par=$count
  (( max_par > budget )) && max_par=$budget
fi
(( max_par < 1 )) && max_par=1

# per (SHORTS_THREADS) is encoder-aware: VideoToolbox lanes share the fixed HW
# encoder so a lone encoder uses all cores and two don't oversubscribe linearly
# — give each the full budget. x264 software encode genuinely competes for
# cores, so keep the divide to stay thrash-safe.
if [[ "$(_shorts_encoder)" == "videotoolbox" ]]; then
  per=$budget
else
  per=$(( budget / max_par )); (( per < 1 )) && per=1
fi
export SHORTS_THREADS="${SHORTS_THREADS:-$per}"

# ---- phase 2-4: per-span lanes --------------------------------------------
# Spans run through max_par lanes. Each lane pulls the next unclaimed span
# and chains edit -> captions -> completion for it before moving on, so early
# spans land in ./output/ while later spans are still editing, and a slow span
# only stalls its own lane. Span-level failures are localized: a failed phase
# cancels the rest of that span only.

# Output folder: a kebab slug of the source title (falls back to the work id),
# so shorts land in output/<title-slug>/ instead of the generic source stem.
slug="$(python3 -c 'import json,re,sys
try:
    d=json.load(open(sys.argv[1]))
    t=(d.get("title") or d.get("id") or d.get("source_id") or "").strip()
except Exception: t=""
s=re.sub(r"[^a-z0-9]+","-",t.lower()).strip("-")[:80]
print(s)' "$ingest_json" 2>/dev/null)"
[[ -n "$slug" ]] || slug="$id"
out_dir="$root/output/$slug"
# Folder is created lazily by save-local when a short is actually saved —
# eagerly mkdir-ing here left empty husk folders behind on failed runs.

# Lane pane is created lazily — a fully-cached span never pays the ~30s
# claude startup. pane_new kills any stale same-name session first.
pane_ready() {
  local pane="$1"
  tmux has-session -t "$pane" 2>/dev/null && return 0
  pane_new "$pane" claude
}

run_span() {
  local i="$1" idx="$2" ed="$3"
  export SHORTS_TL_PHASE=edit

  # A marker from a previous run is stale the moment we re-attempt (or find
  # the phase cached): without this, retried spans stay skipped downstream
  # forever (shorts-8m6).
  rm -f "$dir/clip_${idx}.fail"

  # resume guard: phase 2 already produced this span's vertical + path sidecars.
  # Only honor it when vert.mp4 is NEWER than the segments file it derives from —
  # a re-picked segments.json (new mtime) invalidates a stale vert.mp4 from a
  # prior run whose span range differed (shorts-8m6).
  if [[ -f "$dir/clip_${idx}.vert.mp4" && -f "$dir/clip_${idx}.vert.path" \
        && -f "$dir/clip_${idx}.ctx.path" && "$dir/clip_${idx}.vert.mp4" -nt "$seg_final" ]]; then
    log "[phase 2 / span $idx] cached (vert.mp4 + paths present) — skipping"
    return 0
  fi

  pane_ready "$ed"

  # Read t0/t1 for this span from segments.json
  local t0 t1
  read -r t0 t1 < <(python3 -c '
import json, sys
s = json.load(open(sys.argv[1]))["shorts"][int(sys.argv[2])]
print(s["t0"], s["t1"])' "$seg_final" "$i")

  # Preserve pick-segments' semantic judgment (topic, rationale, suggested
  # title) into a sidecar. This is the context that makes tone/irony legible —
  # without it generate-title reads the clip's literal words and misses the
  # speaker's intent. Carried forward to phase 3 titling.
  local title_ctx="$dir/clip_${idx}.title-context.json"
  python3 -c '
import json, sys
s = json.load(open(sys.argv[1]))["shorts"][int(sys.argv[2])]
json.dump({
    "topic": s.get("topic", ""),
    "rationale": s.get("rationale", ""),
    "title_suggestion": s.get("title_suggestion", ""),
}, open(sys.argv[3], "w"), indent=2)' "$seg_final" "$i" "$title_ctx" || true

  log "[phase 2 / span $idx] editor pane $ed  range=[$t0 .. $t1]"

  # --- bookend-trim (Claude) ---------------------------------------------
  # bookend-trim wants segments+transcript+out; we feed it a 1-span slice.
  local span_in="$dir/clip_${idx}.span.in.json"
  local span_out="$dir/clip_${idx}.span.json"
  python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
i = int(sys.argv[2])
out = {"shorts":[d["shorts"][i]]}
json.dump(out, open(sys.argv[3], "w"))
' "$seg_final" "$i" "$span_in"

  log "[phase 2 / span $idx] bookend-trim"
  if ! timed bookend-trim claude -- bash "$(skill bookend-trim)" "$span_in" "$tx" "$span_out" 6.0 "$dmin" --pane "$ed"; then
    log "[phase 2 / span $idx] bookend-trim FAILED — skipping span"
    echo "bookend-trim" > "$dir/clip_${idx}.fail"
    return 1
  fi
  # --- verify-completeness (Claude) --------------------------------------
  # Does the assembled arc land? Nudge t1 outward within dmax to the landing
  # sentence. Non-fatal: passthrough leaves span_out unchanged. Source coords,
  # before cut — the outward counterpart to the inward-only verify-bookends.
  log "[phase 2 / span $idx] verify-completeness"
  timed verify-completeness claude -- bash "$(skill verify-completeness)" "$span_out" "$tx" "$dir/clip_${idx}.span.complete.json" "$dmax" --pane "$ed" \
    && mv -f "$dir/clip_${idx}.span.complete.json" "$span_out" \
    || log "[phase 2 / span $idx] verify-completeness failed — span unchanged"

  read -r t0 t1 < <(python3 -c '
import json, sys
s = json.load(open(sys.argv[1]))["shorts"][0]
print(s["t0"], s["t1"])' "$span_out")

  # --- cut-clip + rebase (bash); multi-cut spans are assembled here ------
  local clip="$dir/clip_${idx}.mp4"
  local ctx="$dir/clip_${idx}.transcript.json"
  local cuts_json ncuts
  cuts_json="$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1]))["shorts"][0]; print(json.dumps(s.get("cuts") or [[s["t0"],s["t1"]]]))' "$span_out")"
  ncuts="$(python3 -c 'import json,sys; print(len(json.loads(sys.argv[1])))' "$cuts_json")"
  if [[ "$ncuts" -gt 1 ]]; then
    log "[phase 2 / span $idx] cut-clip x$ncuts + concat (multi-cut story)"
    local listf="$dir/clip_${idx}.cuts.txt"; : > "$listf"; local j=0
    while IFS=$'\t' read -r a b; do
      local piece="$dir/clip_${idx}.cut_$(printf '%02d' "$j").mp4"
      # </dev/null: ffmpeg inside cut-clip otherwise slurps this loop's piped
      # stdin and the read consumes only the first cut (multi-cut -> 1 piece).
      bash "$(skill cut-clip)" "$src" "$a" "$b" "$piece" true </dev/null || {
        log "[phase 2 / span $idx] cut-clip piece FAILED"; echo "cut-clip" > "$dir/clip_${idx}.fail"; return 1; }
      # concat-demuxer resolves 'file' paths relative to the list file's dir
      echo "file '$(basename "$piece")'" >> "$listf"; j=$((j + 1))
    done < <(python3 -c 'import json,sys; [print(f"{a}\t{b}") for a,b in json.loads(sys.argv[1])]' "$cuts_json")
    ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i "$listf" -c copy "$clip" \
      || ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i "$listf" "$clip" || {
        log "[phase 2 / span $idx] concat FAILED"; echo "concat" > "$dir/clip_${idx}.fail"; return 1; }
    python3 "$root/assemble.py" "$tx" "$cuts_json" "$ctx" "$clip" || {
      log "[phase 2 / span $idx] assemble FAILED"; echo "assemble" > "$dir/clip_${idx}.fail"; return 1; }
  else
    log "[phase 2 / span $idx] cut-clip"
    timed cut-clip ffmpeg -- bash "$(skill cut-clip)" "$src" "$t0" "$t1" "$clip" true || {
      log "[phase 2 / span $idx] cut-clip FAILED"
      echo "cut-clip" > "$dir/clip_${idx}.fail"; return 1
    }
    python3 "$root/rebase.py" "$tx" "$t0" "$t1" "$ctx" "$clip" || {
      log "[phase 2 / span $idx] rebase FAILED"
      echo "rebase" > "$dir/clip_${idx}.fail"; return 1
    }
  fi

  # --- trim-filler + cut-filler ------------------------------------------
  local keeps="$dir/clip_${idx}.keeps.json"
  local trim_tx="$dir/clip_${idx}.trim.transcript.json"
  log "[phase 2 / span $idx] trim-filler"
  if ! timed trim-filler claude -- bash "$(skill trim-filler)" "$ctx" "$keeps" "$trim_tx" --pane "$ed"; then
    log "[phase 2 / span $idx] trim-filler FAILED"
    echo "trim-filler" > "$dir/clip_${idx}.fail"; return 1
  fi
  local trimmed="$dir/clip_${idx}.trim.mp4"
  timed cut-filler ffmpeg -- bash "$(skill cut-filler)" "$clip" "$keeps" "$trimmed" >/dev/null || {
    log "[phase 2 / span $idx] cut-filler FAILED"
    echo "cut-filler" > "$dir/clip_${idx}.fail"; return 1
  }

  # --- tighten-pace ------------------------------------------------------
  local tight="$dir/clip_${idx}.tight.mp4"
  local tight_tx="$dir/clip_${idx}.tight.transcript.json"
  log "[phase 2 / span $idx] tighten-pace"
  timed tighten-pace ffmpeg -- bash "$(skill tighten-pace)" "$trimmed" "$trim_tx" "$tight" "$tight_tx" >/dev/null || {
    log "[phase 2 / span $idx] tighten-pace FAILED"
    echo "tighten-pace" > "$dir/clip_${idx}.fail"; return 1
  }

  # --- verify-bookends (Claude vision) -----------------------------------
  local vb_out="$dir/clip_${idx}.verify.json"
  local clip_pre="$tight"
  local ctx_pre="$tight_tx"
  if [[ -x "$(skill verify-bookends)" || -f "$(skill verify-bookends)" ]]; then
    log "[phase 2 / span $idx] verify-bookends"
    if timed verify-bookends claude -- bash "$(skill verify-bookends)" "$tight" "$tight_tx" "$vb_out" --pane "$ed"; then
      local action
      action="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("action","keep"))' "$vb_out" 2>/dev/null || echo keep)"
      if [[ "$action" == "drop" ]]; then
        log "[phase 2 / span $idx] verify-bookends -> DROP"
        echo "verify-bookends:drop" > "$dir/clip_${idx}.fail"
        return 1
      elif [[ "$action" == "trim" ]]; then
        local vt0 vt1
        read -r vt0 vt1 < <(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("t0",0), d.get("t1",0))' "$vb_out")
        log "[phase 2 / span $idx] verify-bookends -> trim [$vt0 .. $vt1]"
        local clip2="$dir/clip_${idx}.vb.mp4"
        bash "$(skill cut-clip)" "$tight" "$vt0" "$vt1" "$clip2" true || true
        if [[ -f "$clip2" ]]; then
          local ctx2="$dir/clip_${idx}.vb.transcript.json"
          python3 "$root/rebase.py" "$tight_tx" "$vt0" "$vt1" "$ctx2" "$clip2" || true
          [[ -f "$ctx2" ]] && { clip_pre="$clip2"; ctx_pre="$ctx2"; }
        fi
      fi
    else
      log "[phase 2 / span $idx] verify-bookends: skill error (continuing as keep)"
    fi
  else
    log "[phase 2 / span $idx] verify-bookends skill missing — skipping (will be wired when shorts-zda lands)"
  fi

  # --- fill-vertical -----------------------------------------------------
  local vert="$dir/clip_${idx}.vert.mp4"
  log "[phase 2 / span $idx] fill-vertical"
  timed fill-vertical ffmpeg -- bash "$(skill fill-vertical)" "$clip_pre" "$vert" >/dev/null || {
    log "[phase 2 / span $idx] fill-vertical FAILED"
    echo "fill-vertical" > "$dir/clip_${idx}.fail"; return 1
  }

  # Stash paths for downstream phases
  printf '%s\n' "$vert" > "$dir/clip_${idx}.vert.path"
  printf '%s\n' "$ctx_pre" > "$dir/clip_${idx}.ctx.path"
  printf '%s\n' "$clip_pre" > "$dir/clip_${idx}.src16.path"
  return 0
}

run_phase3_captions() {
  local i="$1" idx="$2" cp_pane="$3"
  export SHORTS_TL_PHASE=captions

  rm -f "$dir/clip_${idx}.fail.captions"

  # resume guard: phase 3 already leveled this span. Only honor it when the
  # leveled output is NEWER than phase 2's vert.mp4 — a re-run phase 2 invalidates
  # a stale leveled.mp4 from a prior span (shorts-8m6).
  if [[ -f "$dir/clip_${idx}.leveled.mp4" && -f "$dir/clip_${idx}.leveled.path" \
        && "$dir/clip_${idx}.leveled.mp4" -nt "$dir/clip_${idx}.vert.mp4" ]]; then
    log "[phase 3 / span $idx] cached (leveled.mp4 present) — skipping"
    return 0
  fi

  pane_ready "$cp_pane"
  local vert; vert="$(cat "$dir/clip_${idx}.vert.path")"
  local ctx;  ctx="$(cat "$dir/clip_${idx}.ctx.path")"
  # Sidecar written by run_span (phase 2); deterministic path, may be absent
  # on older runs — generate-title treats a missing file as no-context.
  local title_ctx="$dir/clip_${idx}.title-context.json"

  log "[phase 3 / span $idx / captions] chunk-captions"
  local chunks="$dir/clip_${idx}.chunks.json"
  timed chunk-captions claude -- bash "$(skill chunk-captions)" "$ctx" "$chunks" --pane "$cp_pane" >/dev/null || {
    log "[phase 3 / span $idx / captions] chunk-captions FAILED"
    echo "chunk-captions" > "$dir/clip_${idx}.fail.captions"; return 1
  }

  # jump-cut: manufacture multi-cam reframe churn on talking-head stretches.
  # Timeline-preserving (audio copied), runs on the clean vertical BEFORE
  # zoom-punch/cutaways/captions so none warp (JUMP_CUT=0 skips).
  local jc="$dir/clip_${idx}.jc.mp4"
  if [[ "${JUMP_CUT:-1}" != "0" ]]; then
    log "[phase 3 / span $idx / captions] jump-cut"
    timed jump-cut ffmpeg -- bash "$(skill jump-cut)" "$vert" "$ctx" "$jc" >/dev/null || cp "$vert" "$jc"
    vert="$jc"
  fi

  # zoom-punch: deterministic punch-ins at RMS-peak words (ZOOM_PUNCH=0 skips).
  # Runs on the clean vertical BEFORE cutaways/captions so neither warps.
  local zoomed="$dir/clip_${idx}.zoom.mp4"
  if [[ "${ZOOM_PUNCH:-1}" != "0" ]]; then
    log "[phase 3 / span $idx / captions] zoom-punch"
    timed zoom-punch ffmpeg -- bash "$(skill zoom-punch)" "$vert" "$ctx" "$zoomed" >/dev/null || cp "$vert" "$zoomed"
  else
    zoomed="$vert"
  fi

  # switch-faces: hard-cut to a non-speaking listener's reaction shot at speech
  # pauses, cropped from the 16:9 source. Timeline-preserving, runs on the clean
  # vertical BEFORE cutaways/captions (which override/burn on top). Solo
  # talking-heads pass through (SWITCH_FACES=0 skips).
  if [[ "${SWITCH_FACES:-1}" != "0" ]]; then
    local src16; src16="$(cat "$dir/clip_${idx}.src16.path" 2>/dev/null || echo "")"
    if [[ -n "$src16" && -f "$src16" ]]; then
      log "[phase 3 / span $idx / captions] switch-faces"
      local switched="$dir/clip_${idx}.sw.mp4"
      timed switch-faces ffmpeg -- bash "$(skill switch-faces)" "$zoomed" "$src16" "$ctx" "$switched" "$chunks" >/dev/null \
        && zoomed="$switched" || true
    fi
  fi

  # broll-pick: Claude anchors -> mcptube/yt-dlp sourced cutaways -> broll_plan.json
  log "[phase 3 / span $idx / captions] broll-pick"
  local broll_plan="$dir/clip_${idx}.broll_plan.json"
  timed broll-pick claude -- bash "$(skill broll-pick)" "$ctx" "$chunks" "$ingest_json" "$broll_plan" --pane "$cp_pane" >/dev/null \
    || echo '{"picks":[],"ingested_video_ids":[]}' > "$broll_plan"

  # broll-composite: full-frame hard-cut cutaways onto the vertical clip (captions burn on top)
  log "[phase 3 / span $idx / captions] broll-composite"
  local brolled="$dir/clip_${idx}.broll.mp4"
  timed broll-composite ffmpeg -- bash "$(skill broll-composite)" "$zoomed" "$broll_plan" "$brolled" >/dev/null || cp "$zoomed" "$brolled"

  # fix-cold-open (PREVENTIVE): proxy-grade the pre-caption clip, then repair the
  # cold open if a route fires (truncate a cold-open b-roll cutaway / re-punch a
  # face-withheld shot0) so frame 1 is the speaker — the front swipe-gate fix.
  # NON-FATAL: passthrough when nothing to fix; captions then burn on the fix.
  # FIX_COLD_OPEN=0 skips the whole pass.
  if [[ "${FIX_COLD_OPEN:-1}" != "0" ]]; then
    GRADE_SKIP_CLAUDE=1 bash "$(skill grade-clip)" "$brolled" >/dev/null 2>&1 || true
    local fcg="${brolled%.*}.grade.json"
    if [[ -f "$fcg" ]]; then
      FIXCO_MODE=preventive bash "$(skill fix-cold-open)" "$brolled" "$fcg" >/dev/null 2>&1 || true
      [[ -f "$dir/clip_${idx}.fixed.mp4" ]] && { brolled="$dir/clip_${idx}.fixed.mp4"; log "[phase 3 / span $idx / captions] fix-cold-open repaired the open"; }
    fi
  fi

  # sfx-beats comedy: meme SFX (vine boom / record scratch) on Claude-marked
  # punchline/irony beats. Audio-only (video stream-copied), so it runs on the
  # pre-overlay clip and its mixed audio rides through the fused compose pass
  # below (which copies audio when no spec carries an audio mix, or amix's it
  # with the title SFX when one does). SFX_COMEDY=0 skips.
  local sfxed="$dir/clip_${idx}.sfx.mp4"
  if [[ "${SFX_COMEDY:-1}" != "0" ]]; then
    log "[phase 3 / span $idx / captions] sfx-beats (comedy)"
    timed sfx-beats claude -- bash "$(skill sfx-beats)" "$brolled" "$ctx" "$sfxed" comedy --pane "$cp_pane" >/dev/null || cp "$brolled" "$sfxed"
  else
    sfxed="$brolled"
  fi

  log "[phase 3 / span $idx / captions] generate-title"
  local title_file="$dir/clip_${idx}.title.txt"
  timed generate-title claude -- bash "$(skill generate-title)" "$ctx" "$ingest_json" "$title_file" "$title_ctx" --pane "$cp_pane" >/dev/null || {
    log "[phase 3 / span $idx / captions] generate-title FAILED"
    echo "generate-title" > "$dir/clip_${idx}.fail.captions"; return 1
  }
  local title; title="$(cat "$title_file")"
  log "[phase 3 / span $idx / captions] title=\"$title\""

  # FUSED CAPTIONS OVERLAY PASS (shorts: 6 overlay encodes -> 2). burn-subtitles,
  # title-transition (single channel glitch style), and brand-overlays each run
  # in OVERLAY_PLAN_ONLY mode — they render their PNG seq / banner PNGs to stable
  # sidecar dirs and emit a base-relative *.overlay.json instead of re-encoding —
  # then ONE compose_overlays pass chains all three filtergraphs onto $sfxed at
  # `mid` quality. title-transition's style SFX wav folds into the cluster audio
  # mix. A .cmpmeta over base+spec mtimes skips the fused encode on an unchanged
  # re-run. Each skill stays independently invocable (standalone = its own encode).
  local sub_spec="$dir/clip_${idx}.sub.overlay.json"
  local title_spec="$dir/clip_${idx}.title.overlay.json"
  local brand_spec="$dir/clip_${idx}.brand.overlay.json"
  local marked="$dir/clip_${idx}.marked.mp4"

  log "[phase 3 / span $idx / captions] overlay plans (burn-subtitles / title-transition / brand-overlays)"
  if ! OVERLAY_PLAN_ONLY=1 bash "$(skill burn-subtitles)" "$sfxed" "$chunks" "$sub_spec" chunks >/dev/null; then
    log "[phase 3 / span $idx / captions] burn-subtitles plan FAILED"
    echo "burn-subtitles" > "$dir/clip_${idx}.fail.captions"; return 1
  fi
  if ! OVERLAY_PLAN_ONLY=1 bash "$(skill title-transition)" "$sfxed" "$title" "$title_spec" >/dev/null; then
    log "[phase 3 / span $idx / captions] title-transition plan FAILED"
    echo "title-transition" > "$dir/clip_${idx}.fail.captions"; return 1
  fi
  OVERLAY_PLAN_ONLY=1 bash "$(skill brand-overlays)" "$sfxed" "$ingest_json" "$brand_spec" >/dev/null \
    || log "[phase 3 / span $idx / captions] brand-overlays plan failed — composing without it"

  # Cluster idempotency: skip the fused encode when the base + every spec is
  # unchanged (same idiom as the per-skill .*meta).
  local cmpmeta="$marked.cmpmeta"
  local cmpsig
  cmpsig="$(_cmpsig "$sfxed" mid "$sub_spec" "$title_spec" "$brand_spec")"
  if [[ -f "$marked" && -f "$cmpmeta" && "$marked" -nt "$sfxed" && "$(cat "$cmpmeta")" == "$cmpsig" ]]; then
    log "[phase 3 / span $idx / captions] overlay-compose-A cache hit"
  else
    log "[phase 3 / span $idx / captions] overlay-compose-A (fused: subtitles + title + brand)"
    local -a aspecs=("$sub_spec" "$title_spec")
    [[ -f "$brand_spec" ]] && aspecs+=("$brand_spec")
    if ! timed overlay-compose-A ffmpeg -- compose_overlays "$sfxed" "$marked" mid "${aspecs[@]}" >/dev/null; then
      log "[phase 3 / span $idx / captions] overlay-compose-A FAILED — serial fallback"
      if ! _overlay_serial_captions "$idx" "$sfxed" "$chunks" "$title" "$ingest_json" "$marked"; then
        echo "overlay-compose-A" > "$dir/clip_${idx}.fail.captions"; return 1
      fi
    fi
    printf '%s' "$cmpsig" > "$cmpmeta"
  fi

  log "[phase 3 / span $idx / captions] loudnorm"
  local leveled="$dir/clip_${idx}.leveled.mp4"
  timed loudnorm ffmpeg -- bash "$(skill loudnorm)" "$marked" "$leveled" >/dev/null || {
    log "[phase 3 / span $idx / captions] loudnorm FAILED"
    echo "loudnorm" > "$dir/clip_${idx}.fail.captions"; return 1
  }
  printf '%s\n' "$leveled" > "$dir/clip_${idx}.leveled.path"
  return 0
}

run_phase4() {
  local i="$1" idx="$2" cm="$3"
  export SHORTS_TL_PHASE=completion

  rm -f "$dir/clip_${idx}.fail.completion"

  # resume guard: phase 4 already saved this span — but only honor the marker if
  # the short it names still exists on disk. A stale marker from a prior run whose
  # output was reaped/removed must NOT swallow the completion phase (shorts-8m6).
  if [[ -f "$dir/clip_${idx}.done.completion" ]]; then
    local saved; saved="$(head -1 "$dir/clip_${idx}.done.completion" 2>/dev/null)"
    if [[ -n "$saved" && -e "$out_dir/$saved" \
          && "$dir/clip_${idx}.done.completion" -nt "$dir/clip_${idx}.leveled.mp4" ]]; then
      log "[phase 4 / span $idx] cached (already saved) — skipping"
      return 0
    fi
    log "[phase 4 / span $idx] stale completion marker ($saved) — re-running"
    rm -f "$dir/clip_${idx}.done.completion"
  fi

  pane_ready "$cm"
  local leveled; leveled="$(cat "$dir/clip_${idx}.leveled.path")"
  local ctx;  ctx="$(cat "$dir/clip_${idx}.ctx.path")"

  # bg-music runs FIRST in this cluster: it is audio-only (video stream-copied),
  # so laying the bed down here lets the fused completion overlay pass below
  # composite the CTA + end-card on the bedded clip and stream-copy the audio
  # through — same delivered audio as the old CTA -> bg-music -> end-card order,
  # one fewer full overlay re-encode.
  log "[phase 4 / span $idx] pick-mood + bg-music"
  local mood_file="$dir/clip_${idx}.mood.txt"
  timed pick-mood claude -- bash "$(skill pick-mood)" "$ctx" "$mood_file" --pane "$cm" >/dev/null || echo "ALL SONGS" > "$mood_file"
  local mood; mood="$(cat "$mood_file")"
  local bedded="$dir/clip_${idx}.final.mp4"
  timed bg-music ffmpeg -- bash "$(skill bg-music)" "$leveled" "$bedded" "$mood" >/dev/null || cp "$leveled" "$bedded"

  # FUSED COMPLETION OVERLAY PASS (CTA + end-card -> ONE encode). Both run in
  # OVERLAY_PLAN_ONLY mode (emit a base-relative *.overlay.json over stable
  # assets, skip their own encode) and one compose_overlays pass chains them onto
  # the bg-music'd clip at `high` quality. .cmpmeta skips an unchanged re-run;
  # each skill stays independently invocable. END_CARD=0 still drops the card.
  local cta_spec="$dir/clip_${idx}.cta.overlay.json"
  local ec_spec="$dir/clip_${idx}.endcard.overlay.json"
  local final="$dir/clip_${idx}.ended.mp4"

  log "[phase 4 / span $idx] overlay plans (like-subscribe-overlay / end-card)"
  OVERLAY_PLAN_ONLY=1 bash "$(skill like-subscribe-overlay)" "$bedded" "$cta_spec" 4.0 >/dev/null \
    || log "[phase 4 / span $idx] like-subscribe-overlay plan failed — composing without it"
  local -a bspecs=()
  [[ -f "$cta_spec" ]] && bspecs+=("$cta_spec")
  if [[ "${END_CARD:-1}" != "0" ]]; then
    OVERLAY_PLAN_ONLY=1 bash "$(skill end-card)" "$bedded" "$ec_spec" >/dev/null \
      && bspecs+=("$ec_spec") \
      || log "[phase 4 / span $idx] end-card plan failed — composing without it"
  fi

  if [[ ${#bspecs[@]} -eq 0 ]]; then
    log "[phase 4 / span $idx] no completion overlays — passthrough"
    cp "$bedded" "$final"
  else
    local cmpmetaB="$final.cmpmeta"
    local cmpsigB
    cmpsigB="$(_cmpsig "$bedded" high "${bspecs[@]}")"
    if [[ -f "$final" && -f "$cmpmetaB" && "$final" -nt "$bedded" && "$(cat "$cmpmetaB")" == "$cmpsigB" ]]; then
      log "[phase 4 / span $idx] overlay-compose-B cache hit"
    else
      log "[phase 4 / span $idx] overlay-compose-B (fused: CTA + end-card)"
      if ! timed overlay-compose-B ffmpeg -- compose_overlays "$bedded" "$final" high "${bspecs[@]}" >/dev/null; then
        log "[phase 4 / span $idx] overlay-compose-B FAILED — serial fallback"
        _overlay_serial_completion "$idx" "$bedded" "$final" || cp "$bedded" "$final"
      fi
      printf '%s' "$cmpsigB" > "$cmpmetaB"
    fi
  fi

  # speed-up: final global retime (SPEED=1.25x) — the last edit step. Keeps every
  # relative beat in sync; qc/cadence/save below run on the delivered clip.
  log "[phase 4 / span $idx] speed-up"
  local sped="$dir/clip_${idx}.sped.mp4"
  timed speed-up ffmpeg -- bash "$(skill speed-up)" "$final" "$sped" >/dev/null || cp "$final" "$sped"
  final="$sped"

  # director-pass: agentic vision QA/repair — a Claude "director" WATCHES the
  # delivered clip and either ships it or applies bounded pixel-safe fixes
  # (tail_trim via cut-clip / music_down via a bg-music re-mix) + surfaces the
  # rest as an honest edit list. The expensive open-ended per-clip loop layered
  # on top of grade-clip + fix-cold-open. Runs on the sped clip with all
  # clip_NN.* sidecars co-located so qc/cadence/save/grade act on the repair.
  # NON-FATAL; idempotent (.dpmeta); DIRECTOR_PASS=0 skips.
  if [[ "${DIRECTOR_PASS:-1}" != "0" ]]; then
    log "[phase 4 / span $idx] director-pass"
    local dpreport="${final%.*}.director.json"
    local dired="${final%.*}.dir.mp4"
    timed director-pass claude -- bash "$(skill director-pass)" "$final" --pane "$cm" >/dev/null 2>&1 || true
    if [[ -f "$dired" ]]; then
      final="$dired"
      local dv; dv="$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d.get("verdict",""),"applied="+",".join(a.get("op","") for a in d.get("applied",[])))' "$dpreport" 2>/dev/null || true)"
      log "[phase 4 / span $idx] director-pass repaired the clip ($dv)"
    fi
  fi

  log "[phase 4 / span $idx] qc-clip"
  local verdict; verdict="$(timed qc-clip det -- bash "$(skill qc-clip)" "$final")"
  local ok; ok="$(printf '%s' "$verdict" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pass"])')"
  if [[ "$ok" != "True" ]]; then
    local reason; reason="$(printf '%s' "$verdict" | python3 -c 'import json,sys; print(json.load(sys.stdin)["reason"])')"
    log "[phase 4 / span $idx] qc FAIL — $reason"
    echo "qc:$reason" > "$dir/clip_${idx}.fail.completion"
    return 1
  fi

  # visual-cadence: non-fatal static-gap measurement (WARN if a stretch exceeds
  # MAX_STATIC_GAP); diagnostic only, never blocks the save.
  timed visual-cadence det -- bash "$(skill visual-cadence)" "$final" "$dir/clip_${idx}.cadence.json" >/dev/null 2>&1 || true
  local cad; cad="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(str(d.get("max_gap","?"))+"s pass="+str(d.get("pass")))' "$dir/clip_${idx}.cadence.json" 2>/dev/null || true)"
  [[ -n "$cad" ]] && log "[phase 4 / span $idx] visual-cadence max_gap=$cad"

  log "[phase 4 / span $idx] name-short"
  local title_file="$dir/clip_${idx}.title.txt"
  local short_name="short_$idx.mp4"
  if [[ -f "$title_file" ]]; then
    short_name="$(bash "$(skill name-short)" "$title_file" 2>/dev/null || echo "short_$idx.mp4")"
    [[ "$short_name" == ".mp4" || -z "$short_name" ]] && short_name="short_$idx.mp4"
  fi

  if [[ -e "$out_dir/$short_name" ]]; then
    short_name="${short_name%.mp4}_$idx.mp4"
  fi

  log "[phase 4 / span $idx] save-local -> $slug/$short_name"
  timed save-local det -- bash "$(skill save-local)" "$final" "$src" "$short_name" "$slug" >/dev/null || {
    log "[phase 4 / span $idx] save-local FAILED"
    echo "save-local" > "$dir/clip_${idx}.fail.completion"
    return 1
  }
  printf '%s\n' "$short_name" > "$dir/clip_${idx}.done.completion"

  # grade-clip: NON-FATAL upload-readiness grade off the DELIVERED clip + its
  # co-located work-dir sidecars (fillplan/chunks/broll/verify/cadence). Grades the
  # work final (rich signals) then mirrors the grade.json next to the saved output
  # clip so --backlog / fix-cold-open / schedule-drip find it in output/. Never
  # blocks the save. GRADE_CLIP=0 disables; proxy-only in-chain (GRADE_SKIP_CLAUDE=1).
  if [[ "${GRADE_CLIP:-1}" != "0" ]]; then
    GRADE_SKIP_CLAUDE="${GRADE_SKIP_CLAUDE:-1}" \
      timed grade-clip det -- bash "$(skill grade-clip)" "$final" >/dev/null 2>&1 || true
    local wgrade="${final%.*}.grade.json"
    if [[ -f "$wgrade" ]]; then
      python3 -c 'import json,sys
d=json.load(open(sys.argv[1])); d["clip"]=sys.argv[2]; d["source"]=sys.argv[3]
json.dump(d, open(sys.argv[4],"w"), indent=2)' \
        "$wgrade" "$out_dir/$short_name" "$slug" "$out_dir/${short_name%.mp4}.grade.json" 2>/dev/null || true
      local gr; gr="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(str(d.get("grade","?"))+"/"+str(d.get("tier","?"))+" caps="+(",".join(d.get("hard_caps") or ["none"])))' "$wgrade" 2>/dev/null || true)"
      [[ -n "$gr" ]] && log "[phase 4 / span $idx] grade-clip $gr"
    fi
  fi
  return 0
}

# ---- per-span lane scheduler ----------------------------------------------
# max_par lane workers each pull the next unclaimed span (mkdir-locked
# counter — atomic across the worker subshells) and run it end-to-end. One
# Claude pane per lane, /clear'd between phases and spans, killed when the
# lane drains. bash 3.2: no wait -n, no associative arrays.

next_span() {
  local lock="$SHORTS_PANE_DIR/span.lock" nf="$SHORTS_PANE_DIR/span.next" n
  until mkdir "$lock" 2>/dev/null; do sleep 0.1; done
  n="$(cat "$nf" 2>/dev/null || echo 0)"
  printf '%s\n' "$((n + 1))" > "$nf"
  rmdir "$lock"
  (( n < count )) || return 1
  printf '%s\n' "$n"
}

lane_clear() {
  tmux has-session -t "$1" 2>/dev/null && pane_chat_clear "$1"
  return 0
}

run_lane() {
  local lane="$1" i idx
  # separate statement: bash 3.2 expands a `local` line's words before any
  # of its assignments land, so $lane is unbound on the same line
  local pane="shorts-$id-lane-$lane"
  export SHORTS_TL_LANE="$lane"
  while i="$(next_span)"; do
    idx="$(printf '%02d' "$((i + 1))")"
    export SHORTS_TL_SPAN="$((i + 1))"
    lane_clear "$pane"
    if ! run_span "$i" "$idx" "$pane"; then
      log "[lane $lane] span $idx FAILED (edit) — next span"
      continue
    fi
    lane_clear "$pane"
    if ! run_phase3_captions "$i" "$idx" "$pane"; then
      log "[lane $lane] span $idx FAILED (captions) — next span"
      continue
    fi
    lane_clear "$pane"
    if ! run_phase4 "$i" "$idx" "$pane"; then
      log "[lane $lane] span $idx FAILED (completion) — next span"
      continue
    fi
    log "[lane $lane] span $idx complete -> output/$slug/"
  done
  tmux kill-session -t "$pane" 2>/dev/null
  return 0
}

rm -f "$SHORTS_PANE_DIR/span.next"
rmdir "$SHORTS_PANE_DIR/span.lock" 2>/dev/null
declare -a lane_pids=()
for ((L = 1; L <= max_par; L++)); do
  ( run_lane "$L" ) &
  lane_pids+=($!)
done
log "[lanes] $count span(s) across $max_par lane(s) (${SHORTS_THREADS} threads each)"
for pid in "${lane_pids[@]}"; do wait "$pid"; done
log "[lanes] all spans complete"

# ---- broll-cleanup --------------------------------------------------------
# Runs ONCE at end of run: evicts only this run's mcptube b-roll ingests +
# local broll/*.mp4 cache. broll_plan.json metadata persists for editors.
shopt -s nullglob
broll_plans=("$dir"/clip_*.broll_plan.json)
shopt -u nullglob
if [[ ${#broll_plans[@]} -gt 0 ]]; then
  log "[cleanup] broll-cleanup (${#broll_plans[@]} plan(s))"
  bash "$(skill broll-cleanup)" "${broll_plans[@]}" >/dev/null 2>&1 || true
fi

# ---- sources-ledger -------------------------------------------------------
# Record this source in work/sources.json (title, url, produced shorts + grades,
# disk footprint, active|reaped status) + a keyed bd memory, so future sessions
# know it's been clipped and reap-source can reclaim its heavy files later.
# Memory half of the disk-hygiene pair; reap-source is the manual cleanup half.
log "[ledger] sources-ledger record $id"
bash "$(skill sources-ledger)" record "$id" >/dev/null 2>&1 || true

# ---- selection-report -----------------------------------------------------
# Write output/<slug>/_selection.json: the shipped shorts (scores + rationale)
# alongside the considered-not-shipped RLM candidate menu + topics, so the other
# arguments are visible next to the produced shorts. Deterministic, non-fatal.
log "[report] selection-report"
bash "$(skill selection-report)" "$dir" "$root/output" >/dev/null 2>&1 || true

# ---- timing-report --------------------------------------------------------
# Fold this run's run_timing.jsonl (+ the run's *.grade.json / *.fail* markers)
# into the machine report (work/<id>/run_timing.json) and the human report
# (output/<slug>/_timing.html). Non-fatal: any error logs and exits 0.
log "[report] timing-report"
python3 "$root/timing-report.py" "$SHORTS_TIMING_LOG" "$dir" "$out_dir/_timing.html" >&2 2>&1 || true

# ---- schedule-drip --------------------------------------------------------
# Runs ONCE at end of run: deterministic greedy scheduler over every graded clip
# in output/. Stages a daily drip into output/_toupload/<date>/ (clip copy +
# metadata.txt) + schedule.json with gap_warnings — the dark-gap / feed-fatigue
# fix. STAGING-HANDOFF ONLY (no upload). Non-fatal, idempotent. SCHEDULE_DRIP=0 skips.
if [[ "${SCHEDULE_DRIP:-1}" != "0" ]]; then
  log "[drip] schedule-drip"
  bash "$(skill schedule-drip)" "${OUTPUT_DIR:-output}" >/dev/null 2>&1 || true
fi

# ---- final summary --------------------------------------------------------
saved=0
failed=0
for ((i = 0; i < count; i++)); do
  idx="$(printf '%02d' "$((i + 1))")"
  if [[ -f "$dir/clip_${idx}.fail" || -f "$dir/clip_${idx}.fail.captions" || -f "$dir/clip_${idx}.fail.completion" ]]; then
    failed=$((failed + 1))
  else
    saved=$((saved + 1))
  fi
done

echo
echo "start: done — $saved/$count saved, $failed failed. Output under ./output/" >&2
exit 0
