#!/usr/bin/env bash
# /start orchestrator. Fans the shorts pipeline across long-lived tmux panes.
#
# Architecture
# ------------
# The orchestrator (this script) is the single driver. Each "pane" is a
# detached tmux session running a plain bash shell — the orchestrator
# sends commands into it via `tmux send-keys` and waits on sentinel files.
#
# For Claude-driven skills, we pass `--pane <name>` and the skill's wrapper
# (via .claude/skills/_lib/pane.sh) routes its prompt through that pane:
#   - write prompt to <_pane>/<name>/<step>/in.txt
#   - send `claude -p < in.txt > out.txt; sync; touch out.done` into pane
#   - wait on out.done, read out.txt
#
# For bash steps, the orchestrator just runs them directly (no pane round-trip
# is needed — bash is already fast).
#
# Why not a long-lived `claude` REPL per pane?
# Driving an interactive `claude` REPL via send-keys is fragile (no reliable
# end-of-response signal). Spawning a fresh `claude -p` per pane round is
# cheap, gives the user a visible-via-attach Claude run, and naturally gives
# each step a clean context window — replacing `clear-and-talk` between
# unrelated jobs in the same pane.

set -uo pipefail

arg="${1:-}"
n="${SHORTS_N:-5}"
dmin="${SHORTS_DMIN:-20}"
dmax="${SHORTS_DMAX:-60}"
max_par="${SHORTS_MAX_PAR:-8}"

if [[ -z "$arg" ]]; then
  cat >&2 <<EOF
usage: start.sh <url-or-source-id>

env knobs:
  SHORTS_N        number of spans to pick (default 5)
  SHORTS_DMIN     min span seconds (default 20)
  SHORTS_DMAX     max span seconds (default 60)
  MCPTUBE_URL     mcptube MCP endpoint (default http://127.0.0.1:9093/mcp)
EOF
  exit 2
fi

root="$(cd "$(dirname "$0")" && pwd)"
cd "$root"
skill() { echo "$root/.claude/skills/$1/$1.sh"; }
log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

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
  url="$arg"
  id="$(printf '%s' "$url" | shasum | cut -c1-10)"
  log "new url $url -> source-id $id"
fi
dir="$root/work/$id"
mkdir -p "$dir/_pane"
export SHORTS_PANE_DIR="$dir/_pane"

# ---- pane management ------------------------------------------------------
declare -a PANES=()

pane_new() {
  local name="$1"
  tmux kill-session -t "$name" 2>/dev/null
  tmux new-session -d -s "$name" -x 200 -y 50 "bash -l" 2>/dev/null
  mkdir -p "$SHORTS_PANE_DIR/$name"
  PANES+=("$name")
}

_cleaned=0
cleanup() {
  (( _cleaned )) && return 0
  _cleaned=1
  log "cleanup: tearing down ${#PANES[@]} pane(s)"
  for p in "${PANES[@]}"; do
    tmux kill-session -t "$p" 2>/dev/null
  done
}
trap cleanup EXIT INT TERM

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
log "[phase 1] launching $sp + $an"
pane_new "$sp"
pane_new "$an"

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
  echo 0 > "$SHORTS_PANE_DIR/$sp/srcprep/exit" 2>/dev/null || { mkdir -p "$SHORTS_PANE_DIR/$sp/srcprep"; echo 0 > "$SHORTS_PANE_DIR/$sp/srcprep/exit"; }
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

# analysis: mcptube add (if URL) — fire-and-poll. The MCP add can run in
# parallel with whisper; we don't need its result before moving on.
if [[ -n "$url" ]]; then
  log "[phase 1] analysis: mcptube add (background)"
  pane_bash "$an" "mcptube_add" \
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
# For each span we spawn its editor pane (phase 2), then captions+broll panes
# (phase 3, parallel), then a completion pane (phase 4). Span-level failures
# are localized: a failed editor cancels phases 3/4 for that span only.

# Output dir cleanup (re-run overwrites)
src_basename="$(basename "$src" .mp4)"
src_id_for_out="$(python3 -c 'import json,sys
try:
    d=json.load(open(sys.argv[1]))
    print(d.get("title") or d.get("id") or d.get("source_id") or "")
except Exception: print("")' "$ingest_json" 2>/dev/null)"
[[ -n "$src_id_for_out" ]] || src_id_for_out="$id"
out_dir="$root/output/$src_id_for_out"
mkdir -p "$out_dir"

run_span() {
  local i="$1"
  local idx; idx="$(printf '%02d' "$((i + 1))")"
  local ed="shorts-$id-editor-$idx"
  local cp_pane="shorts-$id-captions-$idx"
  local br="shorts-$id-broll-$idx"
  local cm="shorts-$id-completion-$idx"

  pane_new "$ed"

  # Read t0/t1 for this span from segments.json
  local t0 t1
  read -r t0 t1 < <(python3 -c '
import json, sys
s = json.load(open(sys.argv[1]))["shorts"][int(sys.argv[2])]
print(s["t0"], s["t1"])' "$seg_final" "$i")

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

  # --- cut-clip + rebase (bash) ------------------------------------------
  local clip="$dir/clip_${idx}.mp4"
  log "[phase 2 / span $idx] cut-clip"
  bash "$(skill cut-clip)" "$src" "$t0" "$t1" "$clip" true || {
    log "[phase 2 / span $idx] cut-clip FAILED"
    echo "cut-clip" > "$dir/clip_${idx}.fail"; return 1
  }
  local ctx="$dir/clip_${idx}.transcript.json"
  python3 "$root/rebase.py" "$tx" "$t0" "$t1" "$ctx" "$clip" || {
    log "[phase 2 / span $idx] rebase FAILED"
    echo "rebase" > "$dir/clip_${idx}.fail"; return 1
  }

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

  # --- fit-vertical ------------------------------------------------------
  local vert="$dir/clip_${idx}.vert.mp4"
  log "[phase 2 / span $idx] fit-vertical"
  bash "$(skill fit-vertical)" "$clip_pre" "$vert" >/dev/null || {
    log "[phase 2 / span $idx] fit-vertical FAILED"
    echo "fit-vertical" > "$dir/clip_${idx}.fail"; return 1
  }

  # Stash paths for downstream phases
  printf '%s\n' "$vert" > "$dir/clip_${idx}.vert.path"
  printf '%s\n' "$ctx_pre" > "$dir/clip_${idx}.ctx.path"
  return 0
}

run_phase3_captions() {
  local i="$1" idx="$2"
  local cp_pane="shorts-$id-captions-$idx"
  pane_new "$cp_pane"
  local vert; vert="$(cat "$dir/clip_${idx}.vert.path")"
  local ctx;  ctx="$(cat "$dir/clip_${idx}.ctx.path")"

  log "[phase 3 / span $idx / captions] chunk-captions"
  local chunks="$dir/clip_${idx}.chunks.json"
  bash "$(skill chunk-captions)" "$ctx" "$chunks" --pane "$cp_pane" >/dev/null || {
    log "[phase 3 / span $idx / captions] chunk-captions FAILED"
    echo "chunk-captions" > "$dir/clip_${idx}.fail.captions"; return 1
  }

  log "[phase 3 / span $idx / captions] burn-subtitles"
  local sub="$dir/clip_${idx}.sub.mp4"
  bash "$(skill burn-subtitles)" "$vert" "$chunks" "$sub" chunks >/dev/null || {
    log "[phase 3 / span $idx / captions] burn-subtitles FAILED"
    echo "burn-subtitles" > "$dir/clip_${idx}.fail.captions"; return 1
  }

  log "[phase 3 / span $idx / captions] generate-title"
  local title_file="$dir/clip_${idx}.title.txt"
  bash "$(skill generate-title)" "$ctx" "$ingest_json" "$title_file" --pane "$cp_pane" >/dev/null || {
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

  log "[phase 3 / span $idx / captions] loudnorm"
  local leveled="$dir/clip_${idx}.leveled.mp4"
  bash "$(skill loudnorm)" "$titled" "$leveled" >/dev/null || {
    log "[phase 3 / span $idx / captions] loudnorm FAILED"
    echo "loudnorm" > "$dir/clip_${idx}.fail.captions"; return 1
  }
  printf '%s\n' "$leveled" > "$dir/clip_${idx}.leveled.path"
  return 0
}

run_phase3_broll() {
  local i="$1" idx="$2"
  local br="shorts-$id-broll-$idx"
  pane_new "$br"
  local vert; vert="$(cat "$dir/clip_${idx}.vert.path")"
  local ctx;  ctx="$(cat "$dir/clip_${idx}.ctx.path")"
  local chunks="$dir/clip_${idx}.chunks.json"
  local plan="$dir/clip_${idx}.broll_plan.json"

  if [[ ! -f "$(skill broll-pick)" ]]; then
    log "[phase 3 / span $idx / broll] broll-pick skill missing — emitting empty plan (shorts-gry pending)"
    printf '%s\n' '{"picks": []}' > "$plan"
    return 0
  fi
  log "[phase 3 / span $idx / broll] broll-pick"
  if ! bash "$(skill broll-pick)" "$vert" "$ctx" "$plan" "$ingest_json" "${chunks:-}" --pane "$br" >/dev/null; then
    log "[phase 3 / span $idx / broll] broll-pick FAILED (continuing with empty plan)"
    printf '%s\n' '{"picks": []}' > "$plan"
  fi
  return 0
}

run_phase4() {
  local i="$1" idx="$2"
  local cm="shorts-$id-completion-$idx"
  pane_new "$cm"
  local leveled; leveled="$(cat "$dir/clip_${idx}.leveled.path")"
  local plan="$dir/clip_${idx}.broll_plan.json"
  local ctx;  ctx="$(cat "$dir/clip_${idx}.ctx.path")"

  local brolled="$dir/clip_${idx}.brolled.mp4"
  if [[ -f "$(skill broll-composite)" && -f "$plan" ]]; then
    log "[phase 4 / span $idx] broll-composite"
    bash "$(skill broll-composite)" "$leveled" "$plan" "$brolled" >/dev/null \
      || cp "$leveled" "$brolled"
  else
    log "[phase 4 / span $idx] broll-composite skill missing (shorts-gry pending) — passthrough"
    cp "$leveled" "$brolled"
  fi

  log "[phase 4 / span $idx] like-subscribe-overlay"
  local ctaed="$dir/clip_${idx}.ctaed.mp4"
  bash "$(skill like-subscribe-overlay)" "$brolled" "$ctaed" 4.0 >/dev/null || cp "$brolled" "$ctaed"

  log "[phase 4 / span $idx] pick-mood + bg-music"
  local mood_file="$dir/clip_${idx}.mood.txt"
  bash "$(skill pick-mood)" "$ctx" "$mood_file" >/dev/null || echo "ALL SONGS" > "$mood_file"
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

  log "[phase 4 / span $idx] save-local"
  bash "$(skill save-local)" "$final" "$src" "short_$idx.mp4" >/dev/null || {
    log "[phase 4 / span $idx] save-local FAILED"
    echo "save-local" > "$dir/clip_${idx}.fail.completion"
    return 1
  }
  return 0
}

# ---- per-span fan-out -----------------------------------------------------
# We process all spans in parallel for phase 2, then phase 3 (both lanes),
# then phase 4.  This matches the spec's "full fan-out" choice.

declare -a span_pids=()
for ((i = 0; i < count; i++)); do
  ( run_span "$i" ) &
  span_pids+=($!)
done
log "[phase 2] $count editor pane(s) running"
for pid in "${span_pids[@]}"; do wait "$pid"; done
log "[phase 2] all editors done"

declare -a p3_pids=()
for ((i = 0; i < count; i++)); do
  idx="$(printf '%02d' "$((i + 1))")"
  if [[ -f "$dir/clip_${idx}.fail" ]]; then
    log "[phase 3] span $idx skipped (editor failed: $(cat "$dir/clip_${idx}.fail"))"
    continue
  fi
  ( run_phase3_captions "$i" "$idx" ) &
  p3_pids+=($!)
  ( run_phase3_broll "$i" "$idx" ) &
  p3_pids+=($!)
done
log "[phase 3] ${#p3_pids[@]} captions+broll pane(s) running"
for pid in "${p3_pids[@]}"; do wait "$pid"; done
log "[phase 3] all captions+broll done"

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
  ( run_phase4 "$i" "$idx" ) &
  p4_pids+=($!)
done
log "[phase 4] ${#p4_pids[@]} completion pane(s) running"
for pid in "${p4_pids[@]}"; do wait "$pid"; done

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
