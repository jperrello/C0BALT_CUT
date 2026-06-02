#!/usr/bin/env bash
# shorts: YouTube URL -> finished vertical shorts in ./output/<source>/
#
# Drives the atomic skill chain. Each skill is invoked independently; data
# passes as JSON on disk under ./work/<id>/. Re-running is cheap (skills
# cache on mtime).
set -uo pipefail

url="${1:-}"
n="${2:-5}"
dmin="${3:-20}"
dmax="${4:-60}"

if [[ -z "$url" ]]; then
  echo "usage: shorts.sh <youtube-url> [n=5] [dmin=20] [dmax=60]" >&2
  exit 2
fi

root="$(cd "$(dirname "$0")" && pwd)"
skill() { echo "$root/.claude/skills/$1/$1.sh"; }

step() { echo; echo ">>> $*" >&2; }
die() { echo "shorts: FAILED — $*" >&2; exit 1; }

# 1. ingest -----------------------------------------------------------------
skipped=0

step "ingest $url"
meta="$(bash "$(skill ingest)" "$url")" || die "ingest"
id="$(printf '%s' "$meta" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
src="$(printf '%s' "$meta" | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])')"
dir="$(dirname "$src")"
ingest_json="$dir/ingest.json"
echo "shorts: work dir $dir" >&2

# 2. transcribe -------------------------------------------------------------
step "transcribe"
transcript="$dir/transcript.json"
bash "$(skill transcribe)" "$src" "$transcript" >/dev/null || die "transcribe"

# 3. segment-topics ---------------------------------------------------------
step "segment-topics"
topics="$dir/topics.json"
bash "$(skill segment-topics)" "$transcript" "$topics" >/dev/null || die "segment-topics"

# 6. pick-segments ----------------------------------------------------------
step "pick-segments (n=$n)"
segments_raw="$dir/segments.raw.json"
bash "$(skill pick-segments)" "$transcript" "$segments_raw" "$n" "$dmin" "$dmax" "$topics" >/dev/null || die "pick-segments"

# 7. verify-coherence (tightens incoherent spans) --------------------------
step "verify-coherence"
segments_coh="$dir/segments.coherent.json"
bash "$(skill verify-coherence)" "$segments_raw" "$transcript" "$segments_coh" "$dmin" >/dev/null || die "verify-coherence"

# 7b. bookend-trim (snap to sentence boundaries) ---------------------------
step "bookend-trim"
segments="$dir/segments.json"
bash "$(skill bookend-trim)" "$segments_coh" "$transcript" "$segments" 6.0 "$dmin" >/dev/null || die "bookend-trim"

count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["shorts"]))' "$segments")"
echo "shorts: $count surviving span(s) after coherence check" >&2
[[ "$count" -gt 0 ]] || die "no spans survived verify-coherence"

# 8. per-span render --------------------------------------------------------
saved=0
for ((i = 0; i < count; i++)); do
  idx="$(printf '%02d' "$((i + 1))")"
  (
    set -e
    read -r t0 t1 < <(python3 -c '
import json,sys
s=json.load(open(sys.argv[1]))["shorts"][int(sys.argv[2])]
print(s["t0"], s["t1"])' "$segments" "$i")

    echo ">>> short $idx  [$t0 - $t1]" >&2

    clip="$dir/clip_$idx.mp4"
    bash "$(skill cut-clip)" "$src" "$t0" "$t1" "$clip" true

    # rebase transcript into clip-local time
    ctx="$dir/clip_$idx.transcript.json"
    python3 "$root/rebase.py" "$transcript" "$t0" "$t1" "$ctx" "$clip"

    # trim-filler: Claude marks filler / trail-offs / digressive asides for removal
    keeps="$dir/clip_$idx.keeps.json"
    trim_tx="$dir/clip_$idx.trim.transcript.json"
    bash "$(skill trim-filler)" "$ctx" "$keeps" "$trim_tx" >/dev/null
    trimmed="$dir/clip_$idx.trim.mp4"
    bash "$(skill cut-filler)" "$clip" "$keeps" "$trimmed" >/dev/null
    clip="$trimmed"
    ctx="$trim_tx"

    # tighten-pace: collapse inter-word silences > gap_max (default 0.18s)
    tight="$dir/clip_$idx.tight.mp4"
    tight_tx="$dir/clip_$idx.tight.transcript.json"
    bash "$(skill tighten-pace)" "$clip" "$ctx" "$tight" "$tight_tx" >/dev/null
    clip="$tight"
    ctx="$tight_tx"

    # verify-bookends: vision check on first/last 1.5s; may issue inward second cut
    vb_decision="$dir/clip_$idx.verify.json"
    bash "$(skill verify-bookends)" "$clip" "$ctx" "$vb_decision" >/dev/null || true
    vb_action="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("action","keep"))' "$vb_decision" 2>/dev/null || echo keep)"
    echo "    verify-bookends: $vb_action" >&2
    if [[ "$vb_action" == "drop" ]]; then
      echo "short $idx: DROP per verify-bookends" >&2
      exit 7
    fi
    if [[ "$vb_action" == "trim" ]]; then
      vb_t0="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["t0"])' "$vb_decision")"
      vb_t1="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["t1"])' "$vb_decision")"
      vbclip="$dir/clip_$idx.verified.mp4"
      bash "$(skill cut-clip)" "$clip" "$vb_t0" "$vb_t1" "$vbclip" true >/dev/null
      vb_tx="$dir/clip_$idx.verified.transcript.json"
      python3 "$root/rebase.py" "$ctx" "$vb_t0" "$vb_t1" "$vb_tx" "$vbclip"
      clip="$vbclip"
      ctx="$vb_tx"
    fi

    vert="$dir/clip_$idx.vert.mp4"
    bash "$(skill fill-vertical)" "$clip" "$vert" >/dev/null

    # chunk-captions: clip transcript -> phrase chunks (kills the rolling scroll)
    # (moved ahead of broll-pick so cutaway windows snap to whole chunk boundaries)
    chunks="$dir/clip_$idx.chunks.json"
    bash "$(skill chunk-captions)" "$ctx" "$chunks" >/dev/null

    # broll-pick: Claude anchors -> mcptube/yt-dlp sourced cutaways -> broll_plan.json
    broll_plan="$dir/clip_$idx.broll_plan.json"
    bash "$(skill broll-pick)" "$ctx" "$chunks" "$ingest_json" "$broll_plan" >/dev/null || echo '{"picks":[],"ingested_video_ids":[]}' > "$broll_plan"

    # broll-composite: full-frame hard-cut cutaways onto the vertical clip (captions burn on top)
    brolled="$dir/clip_$idx.broll.mp4"
    bash "$(skill broll-composite)" "$vert" "$broll_plan" "$brolled" >/dev/null || cp "$vert" "$brolled"

    sub="$dir/clip_$idx.sub.mp4"
    bash "$(skill burn-subtitles)" "$brolled" "$chunks" "$sub" chunks >/dev/null

    # generate-title: per-clip third-person ALL-CAPS hook title
    title_file="$dir/clip_$idx.title.txt"
    bash "$(skill generate-title)" "$ctx" "$ingest_json" "$title_file" >/dev/null
    title="$(cat "$title_file")"
    echo "    title: $title" >&2

    titled="$dir/clip_$idx.titled.mp4"
    bash "$(skill title-transition)" "$sub" "$title" "$titled" >/dev/null

    leveled="$dir/clip_$idx.leveled.mp4"
    bash "$(skill loudnorm)" "$titled" "$leveled"

    # like-subscribe-overlay: animated CTA in the last 4s
    ctaed="$dir/clip_$idx.ctaed.mp4"
    bash "$(skill like-subscribe-overlay)" "$leveled" "$ctaed" 4.0 >/dev/null || cp "$leveled" "$ctaed"

    # pick-mood: Claude reads clip transcript and picks a ./songs/<mood>/ folder
    mood_file="$dir/clip_$idx.mood.txt"
    bash "$(skill pick-mood)" "$ctx" "$mood_file" >/dev/null || echo "ALL SONGS" > "$mood_file"
    mood="$(cat "$mood_file")"
    echo "    mood: $mood" >&2

    # bg-music: trendy looped bed at vol=0.12 (~-18dB) under broadcast-leveled speech
    final="$dir/clip_$idx.final.mp4"
    bash "$(skill bg-music)" "$ctaed" "$final" "$mood" >/dev/null || cp "$ctaed" "$final"

    verdict="$(bash "$(skill qc-clip)" "$final")"
    ok="$(printf '%s' "$verdict" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pass"])')"
    if [[ "$ok" != "True" ]]; then
      reason="$(printf '%s' "$verdict" | python3 -c 'import json,sys; print(json.load(sys.stdin)["reason"])')"
      echo "short $idx: QC FAIL — $reason" >&2
      exit 3
    fi

    bash "$(skill save-local)" "$final" "$src" "short_$idx.mp4" >/dev/null
  )
  rc=$?
  if [[ $rc -eq 0 ]]; then
    saved=$((saved + 1))
  elif [[ $rc -eq 7 ]]; then
    skipped=$((skipped + 1))
    echo "short $idx: skipped (verify-bookends drop)" >&2
  else
    echo "short $idx: skipped (rc=$rc)" >&2
  fi
done

# broll-cleanup: runs ONCE at end of run — evicts only this run's mcptube b-roll
# ingests + local broll/*.mp4 cache. broll_plan.json metadata persists for editors.
shopt -s nullglob
plans=("$dir"/clip_*.broll_plan.json)
shopt -u nullglob
if [[ ${#plans[@]} -gt 0 ]]; then
  step "broll-cleanup"
  bash "$(skill broll-cleanup)" "${plans[@]}" >/dev/null 2>&1 || true
fi

echo
echo "shorts: done — $saved/$count short(s) saved under ./output/ ($skipped dropped by verify-bookends)" >&2
