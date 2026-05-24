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

# 3. detect-faces -----------------------------------------------------------
step "detect-faces"
faces="$dir/faces.json"
bash "$(skill detect-faces)" "$src" "$faces" >/dev/null || die "detect-faces"

# 4. pick-speaker (whole video) --------------------------------------------
step "pick-speaker"
speaker="$dir/speaker.json"
bash "$(skill pick-speaker)" "$transcript" "$faces" "$src" "$speaker" >/dev/null || die "pick-speaker"

# 5. segment-topics ---------------------------------------------------------
step "segment-topics"
topics="$dir/topics.json"
bash "$(skill segment-topics)" "$transcript" "$topics" >/dev/null || die "segment-topics"

# 6. pick-segments ----------------------------------------------------------
step "pick-segments (n=$n)"
segments_raw="$dir/segments.raw.json"
bash "$(skill pick-segments)" "$transcript" "$segments_raw" "$n" "$dmin" "$dmax" "$topics" >/dev/null || die "pick-segments"

# 7. verify-coherence (tightens incoherent spans) --------------------------
step "verify-coherence"
segments="$dir/segments.json"
bash "$(skill verify-coherence)" "$segments_raw" "$transcript" "$segments" "$dmin" >/dev/null || die "verify-coherence"

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

    # rebase transcript + speaker track into clip-local time
    ctx="$dir/clip_$idx.transcript.json"
    cspk="$dir/clip_$idx.speaker.json"
    python3 "$root/rebase.py" "$transcript" "$speaker" "$t0" "$t1" "$ctx" "$cspk" "$clip"

    vert="$dir/clip_$idx.vert.mp4"
    bash "$(skill fit-vertical)" "$clip" "$vert" >/dev/null

    # chunk-captions: clip transcript -> phrase chunks (kills the rolling scroll)
    chunks="$dir/clip_$idx.chunks.json"
    bash "$(skill chunk-captions)" "$ctx" "$chunks" >/dev/null

    sub="$dir/clip_$idx.sub.mp4"
    bash "$(skill burn-subtitles)" "$vert" "$chunks" "$sub" chunks >/dev/null

    # generate-title: per-clip third-person ALL-CAPS hook title
    title_file="$dir/clip_$idx.title.txt"
    bash "$(skill generate-title)" "$ctx" "$ingest_json" "$title_file" >/dev/null
    title="$(cat "$title_file")"
    echo "    title: $title" >&2

    titled="$dir/clip_$idx.titled.mp4"
    bash "$(skill title-transition)" "$sub" "$title" "$titled" >/dev/null

    final="$dir/clip_$idx.final.mp4"
    bash "$(skill loudnorm)" "$titled" "$final"

    verdict="$(bash "$(skill qc-clip)" "$final")"
    ok="$(printf '%s' "$verdict" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pass"])')"
    if [[ "$ok" != "True" ]]; then
      reason="$(printf '%s' "$verdict" | python3 -c 'import json,sys; print(json.load(sys.stdin)["reason"])')"
      echo "short $idx: QC FAIL — $reason" >&2
      exit 3
    fi

    bash "$(skill save-local)" "$final" "$src" "short_$idx.mp4" >/dev/null
  ) && saved=$((saved + 1)) || echo "short $idx: skipped" >&2
done

echo
echo "shorts: done — $saved/$count short(s) saved under ./output/" >&2
