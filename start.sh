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
# handles one source transcript; each editor/captions/completion pane handles
# one span. If these panes are ever reused across sources/spans, clear first.

set -uo pipefail

# This orchestrator may be invoked from inside a Claude Code session; child
# `claude -p` invocations (in panes or fallback) refuse to nest unless these
# are unset. Strip them at the very top so every child inherits a clean env.
unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT

n="${SHORTS_N:-5}"
dmin="${SHORTS_DMIN:-20}"
dmax="${SHORTS_DMAX:-60}"
max_par="${SHORTS_MAX_PAR:-1}"
(( max_par < 1 )) && max_par=1

# Divide cores across the spans we run at once and leave one free so the
# machine stays usable. Each ffmpeg (vt_threads) and whisper run honors these.
ncpu="$(sysctl -n hw.logicalcpu 2>/dev/null || echo 8)"
budget=$(( ncpu - 1 )); (( budget < 1 )) && budget=1
per=$(( budget / max_par )); (( per < 1 )) && per=1
export SHORTS_THREADS="${SHORTS_THREADS:-$per}"
export SHORTS_WHISPER_THREADS="${SHORTS_WHISPER_THREADS:-$per}"

if [[ $# -lt 1 ]]; then
  cat >&2 <<EOF
usage: start.sh <url-or-source-id> [<url-or-source-id> ...]

Pass multiple URLs / video IDs / source-ids to process them sequentially.
Each video's tmux panes are torn down before the next one starts.
After a successful run on a YouTube ID, edited_at is stamped in mcptube.

env knobs:
  SHORTS_N        number of spans to pick (default 5)
  SHORTS_DMIN     min span seconds (default 20)
  SHORTS_DMAX     max span seconds (default 60)
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
    pane_chat_clear "$name"
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
  tmux send-keys -t "$pane" -l -- "/clear"
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
log "[phase 1 / analysis] segment-topics"
bash "$(skill segment-topics)" "$tx" "$topics" --pane "$an" || { log "FATAL: segment-topics"; exit 3; }
log "[phase 1 / analysis] pick-segments"
bash "$(skill pick-segments)" "$tx" "$seg_raw" "$n" "$dmin" "$dmax" "$topics" --pane "$an" || { log "FATAL: pick-segments"; exit 3; }
log "[phase 1 / analysis] verify-coherence"
bash "$(skill verify-coherence)" "$seg_raw" "$tx" "$seg_coh" "$dmin" --pane "$an" || { log "FATAL: verify-coherence"; exit 3; }

# bookend-trim was moved to phase 2 per spec; coherent spans become segments.json
# directly as the per-span input. Each editor pane will re-snap its own span.
cp "$seg_coh" "$seg_final"
count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["shorts"]))' "$seg_final")"
log "[phase 1] $count span(s) survived coherence check"
[[ "$count" -gt 0 ]] || { log "FATAL: no spans survived"; exit 4; }

# ---- phase 2-4: per-span fan-out -----------------------------------------
# For each span we spawn its editor pane (phase 2), then captions pane
# (phase 3), then a completion pane (phase 4). Span-level failures
# are localized: a failed editor cancels phases 3/4 for that span only.

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

run_span() {
  local i="$1"
  local idx; idx="$(printf '%02d' "$((i + 1))")"
  local ed="shorts-$id-editor-$idx"
  local cp_pane="shorts-$id-captions-$idx"
  local cm="shorts-$id-completion-$idx"

  # resume guard: phase 2 already produced this span's vertical + path sidecars
  if [[ -f "$dir/clip_${idx}.vert.mp4" && -f "$dir/clip_${idx}.vert.path" && -f "$dir/clip_${idx}.ctx.path" ]]; then
    log "[phase 2 / span $idx] cached (vert.mp4 + paths present) — skipping"
    return 0
  fi

  pane_new "$ed" claude

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
  if ! bash "$(skill bookend-trim)" "$span_in" "$tx" "$span_out" 6.0 "$dmin" --pane "$ed"; then
    log "[phase 2 / span $idx] bookend-trim FAILED — skipping span"
    echo "bookend-trim" > "$dir/clip_${idx}.fail"
    return 1
  fi
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
    bash "$(skill cut-clip)" "$src" "$t0" "$t1" "$clip" true || {
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
  if ! bash "$(skill trim-filler)" "$ctx" "$keeps" "$trim_tx" --pane "$ed"; then
    log "[phase 2 / span $idx] trim-filler FAILED"
    echo "trim-filler" > "$dir/clip_${idx}.fail"; return 1
  fi
  local trimmed="$dir/clip_${idx}.trim.mp4"
  bash "$(skill cut-filler)" "$clip" "$keeps" "$trimmed" >/dev/null || {
    log "[phase 2 / span $idx] cut-filler FAILED"
    echo "cut-filler" > "$dir/clip_${idx}.fail"; return 1
  }

  # --- tighten-pace ------------------------------------------------------
  local tight="$dir/clip_${idx}.tight.mp4"
  local tight_tx="$dir/clip_${idx}.tight.transcript.json"
  log "[phase 2 / span $idx] tighten-pace"
  bash "$(skill tighten-pace)" "$trimmed" "$trim_tx" "$tight" "$tight_tx" >/dev/null || {
    log "[phase 2 / span $idx] tighten-pace FAILED"
    echo "tighten-pace" > "$dir/clip_${idx}.fail"; return 1
  }

  # --- verify-bookends (Claude vision) -----------------------------------
  local vb_out="$dir/clip_${idx}.verify.json"
  local clip_pre="$tight"
  local ctx_pre="$tight_tx"
  if [[ -x "$(skill verify-bookends)" || -f "$(skill verify-bookends)" ]]; then
    log "[phase 2 / span $idx] verify-bookends"
    if bash "$(skill verify-bookends)" "$tight" "$tight_tx" "$vb_out" --pane "$ed"; then
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
  bash "$(skill fill-vertical)" "$clip_pre" "$vert" >/dev/null || {
    log "[phase 2 / span $idx] fill-vertical FAILED"
    echo "fill-vertical" > "$dir/clip_${idx}.fail"; return 1
  }

  # Stash paths for downstream phases
  printf '%s\n' "$vert" > "$dir/clip_${idx}.vert.path"
  printf '%s\n' "$ctx_pre" > "$dir/clip_${idx}.ctx.path"
  return 0
}

run_phase3_captions() {
  local i="$1" idx="$2"
  local cp_pane="shorts-$id-captions-$idx"

  # resume guard: phase 3 already leveled this span
  if [[ -f "$dir/clip_${idx}.leveled.mp4" && -f "$dir/clip_${idx}.leveled.path" ]]; then
    log "[phase 3 / span $idx] cached (leveled.mp4 present) — skipping"
    return 0
  fi

  pane_new "$cp_pane" claude
  local vert; vert="$(cat "$dir/clip_${idx}.vert.path")"
  local ctx;  ctx="$(cat "$dir/clip_${idx}.ctx.path")"
  # Sidecar written by run_span (phase 2); deterministic path, may be absent
  # on older runs — generate-title treats a missing file as no-context.
  local title_ctx="$dir/clip_${idx}.title-context.json"

  log "[phase 3 / span $idx / captions] chunk-captions"
  local chunks="$dir/clip_${idx}.chunks.json"
  bash "$(skill chunk-captions)" "$ctx" "$chunks" --pane "$cp_pane" >/dev/null || {
    log "[phase 3 / span $idx / captions] chunk-captions FAILED"
    echo "chunk-captions" > "$dir/clip_${idx}.fail.captions"; return 1
  }

  # broll-pick: Claude anchors -> mcptube/yt-dlp sourced cutaways -> broll_plan.json
  log "[phase 3 / span $idx / captions] broll-pick"
  local broll_plan="$dir/clip_${idx}.broll_plan.json"
  bash "$(skill broll-pick)" "$ctx" "$chunks" "$ingest_json" "$broll_plan" --pane "$cp_pane" >/dev/null \
    || echo '{"picks":[],"ingested_video_ids":[]}' > "$broll_plan"

  # broll-composite: full-frame hard-cut cutaways onto the vertical clip (captions burn on top)
  log "[phase 3 / span $idx / captions] broll-composite"
  local brolled="$dir/clip_${idx}.broll.mp4"
  bash "$(skill broll-composite)" "$vert" "$broll_plan" "$brolled" >/dev/null || cp "$vert" "$brolled"

  log "[phase 3 / span $idx / captions] burn-subtitles"
  local sub="$dir/clip_${idx}.sub.mp4"
  bash "$(skill burn-subtitles)" "$brolled" "$chunks" "$sub" chunks >/dev/null || {
    log "[phase 3 / span $idx / captions] burn-subtitles FAILED"
    echo "burn-subtitles" > "$dir/clip_${idx}.fail.captions"; return 1
  }

  log "[phase 3 / span $idx / captions] generate-title"
  local title_file="$dir/clip_${idx}.title.txt"
  bash "$(skill generate-title)" "$ctx" "$ingest_json" "$title_file" "$title_ctx" --pane "$cp_pane" >/dev/null || {
    log "[phase 3 / span $idx / captions] generate-title FAILED"
    echo "generate-title" > "$dir/clip_${idx}.fail.captions"; return 1
  }
  local title; title="$(cat "$title_file")"
  log "[phase 3 / span $idx / captions] title=\"$title\""

  log "[phase 3 / span $idx / captions] title-transition"
  local titled="$dir/clip_${idx}.titled.mp4"
  bash "$(skill title-transition)" "$sub" "$title" "$titled" >/dev/null || {
    log "[phase 3 / span $idx / captions] title-transition FAILED"
    echo "title-transition" > "$dir/clip_${idx}.fail.captions"; return 1
  }

  log "[phase 3 / span $idx / captions] source-credit"
  local credited="$dir/clip_${idx}.credited.mp4"
  bash "$(skill source-credit)" "$titled" "$ingest_json" "$credited" >/dev/null || {
    log "[phase 3 / span $idx / captions] source-credit FAILED (continuing without credit)"
    cp "$titled" "$credited"
  }

  log "[phase 3 / span $idx / captions] watermark"
  local marked="$dir/clip_${idx}.marked.mp4"
  bash "$(skill watermark)" "$credited" "$marked" >/dev/null || {
    log "[phase 3 / span $idx / captions] watermark FAILED (continuing without mark)"
    cp "$credited" "$marked"
  }

  log "[phase 3 / span $idx / captions] loudnorm"
  local leveled="$dir/clip_${idx}.leveled.mp4"
  bash "$(skill loudnorm)" "$marked" "$leveled" >/dev/null || {
    log "[phase 3 / span $idx / captions] loudnorm FAILED"
    echo "loudnorm" > "$dir/clip_${idx}.fail.captions"; return 1
  }
  printf '%s\n' "$leveled" > "$dir/clip_${idx}.leveled.path"
  return 0
}

run_phase4() {
  local i="$1" idx="$2"
  local cm="shorts-$id-completion-$idx"

  # resume guard: phase 4 already saved this span
  if [[ -f "$dir/clip_${idx}.done.completion" ]]; then
    log "[phase 4 / span $idx] cached (already saved) — skipping"
    return 0
  fi

  pane_new "$cm" claude
  local leveled; leveled="$(cat "$dir/clip_${idx}.leveled.path")"
  local ctx;  ctx="$(cat "$dir/clip_${idx}.ctx.path")"

  log "[phase 4 / span $idx] like-subscribe-overlay"
  local ctaed="$dir/clip_${idx}.ctaed.mp4"
  bash "$(skill like-subscribe-overlay)" "$leveled" "$ctaed" 4.0 >/dev/null || cp "$leveled" "$ctaed"

  log "[phase 4 / span $idx] pick-mood + bg-music"
  local mood_file="$dir/clip_${idx}.mood.txt"
  bash "$(skill pick-mood)" "$ctx" "$mood_file" --pane "$cm" >/dev/null || echo "ALL SONGS" > "$mood_file"
  local mood; mood="$(cat "$mood_file")"
  local final="$dir/clip_${idx}.final.mp4"
  bash "$(skill bg-music)" "$ctaed" "$final" "$mood" >/dev/null || cp "$ctaed" "$final"

  log "[phase 4 / span $idx] qc-clip"
  local verdict; verdict="$(bash "$(skill qc-clip)" "$final")"
  local ok; ok="$(printf '%s' "$verdict" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pass"])')"
  if [[ "$ok" != "True" ]]; then
    local reason; reason="$(printf '%s' "$verdict" | python3 -c 'import json,sys; print(json.load(sys.stdin)["reason"])')"
    log "[phase 4 / span $idx] qc FAIL — $reason"
    echo "qc:$reason" > "$dir/clip_${idx}.fail.completion"
    return 1
  fi

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
  bash "$(skill save-local)" "$final" "$src" "$short_name" "$slug" >/dev/null || {
    log "[phase 4 / span $idx] save-local FAILED"
    echo "save-local" > "$dir/clip_${idx}.fail.completion"
    return 1
  }
  printf '%s\n' "$short_name" > "$dir/clip_${idx}.done.completion"
  return 0
}

# ---- per-span fan-out -----------------------------------------------------
# Spans run at most $max_par at a time (default 1 = sequential). Past runs
# launched every span at once with each ffmpeg/whisper grabbing all cores,
# which thrashed the CPU. throttle blocks until a slot frees up (bash 3.2 has
# no `wait -n`, so we poll the live pids).

throttle() {
  local max="$1"; shift
  while :; do
    local alive=0 p
    for p in "$@"; do
      [[ -n "$p" ]] && kill -0 "$p" 2>/dev/null && alive=$((alive + 1))
    done
    (( alive < max )) && return
    sleep 0.5
  done
}

declare -a span_pids=()
for ((i = 0; i < count; i++)); do
  throttle "$max_par" "${span_pids[@]:-}"
  ( run_span "$i" ) &
  span_pids+=($!)
done
log "[phase 2] $count span(s), up to $max_par at a time (${SHORTS_THREADS} threads each)"
for pid in "${span_pids[@]}"; do wait "$pid"; done
log "[phase 2] all editors done"

declare -a p3_pids=()
for ((i = 0; i < count; i++)); do
  idx="$(printf '%02d' "$((i + 1))")"
  if [[ -f "$dir/clip_${idx}.fail" ]]; then
    log "[phase 3] span $idx skipped (editor failed: $(cat "$dir/clip_${idx}.fail"))"
    continue
  fi
  throttle "$max_par" "${p3_pids[@]:-}"
  ( run_phase3_captions "$i" "$idx" ) &
  p3_pids+=($!)
done
log "[phase 3] ${#p3_pids[@]} captions pane(s) running"
for pid in "${p3_pids[@]}"; do wait "$pid"; done
log "[phase 3] all captions done"

declare -a p4_pids=()
for ((i = 0; i < count; i++)); do
  idx="$(printf '%02d' "$((i + 1))")"
  if [[ -f "$dir/clip_${idx}.fail" ]]; then
    log "[phase 4] span $idx skipped (editor failed)"
    continue
  fi
  if [[ -f "$dir/clip_${idx}.fail.captions" ]]; then
    log "[phase 4] span $idx skipped (captions failed: $(cat "$dir/clip_${idx}.fail.captions"))"
    continue
  fi
  throttle "$max_par" "${p4_pids[@]:-}"
  ( run_phase4 "$i" "$idx" ) &
  p4_pids+=($!)
done
log "[phase 4] ${#p4_pids[@]} completion pane(s) running"
for pid in "${p4_pids[@]}"; do wait "$pid"; done

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
