#!/usr/bin/env bash
# sfx-beats: mix synthesized SFX into a clip.
#   tension mode (default): riser/hit/stinger at transcript pivot + RMS peak.
#   comedy mode: Claude marks punchline/irony beats -> vine boom / record
#   scratch. Canonical chain runs comedy after burn-subtitles. (The "ding"
#   insight/aha-moment bell is retired.)
set -euo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

input="${1:-}"
transcript="${2:-}"
out="${3:-}"
mode="${4:-tension}"
rms_in="${5:-}"

if [[ -z "$input" || -z "$transcript" || -z "$out" ]]; then
  echo "usage: sfx-beats.sh <input> <transcript.json> <out> [mode=tension|comedy] [audio_rms.json]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "sfx-beats: input not found: $input" >&2; exit 2; }
[[ -f "$transcript" ]] || { echo "sfx-beats: transcript not found: $transcript" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
meta="$out.sfxmeta"
in_mtime="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
tx_mtime="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
sig="$in_mtime|$tx_mtime|$mode"

if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  o="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$o" -ge "$in_mtime" && "$o" -ge "$tx_mtime" ]]; then
    echo "sfx-beats: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

dur="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$input")"
[[ -n "$dur" ]] || { echo "sfx-beats: could not read duration" >&2; exit 1; }

has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$input" 2>/dev/null || true)"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$(dirname "$out")"

passthrough() {
  ffmpeg -y -hide_banner -loglevel error -i "$input" -c copy "$out" 2>/dev/null \
    || cp "$input" "$out"
  printf '%s' "$sig" > "$meta"
  echo "sfx-beats: $1 — passthrough" >&2
  echo "$out"
}

if [[ "$mode" == "comedy" ]]; then
  n_words="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("words",[])))' "$transcript")"
  if [[ "$n_words" -lt 8 ]]; then
    passthrough "too few words ($n_words)"; exit 0
  fi
  python3 "$here/comedy_prompt.py" "$transcript" > "$tmp/prompt.txt"
  if ! run_claude_step sfx-comedy "$tmp/prompt.txt" "$tmp/reply.txt" 2>"$tmp/claude.err"; then
    echo "sfx-beats: claude step failed" >&2
    cat "$tmp/claude.err" >&2
    passthrough "claude failure"; exit 0
  fi
  python3 "$here/parse_comedy.py" "$tmp/reply.txt" "$dur" > "$tmp/plan.json"
  plan_ok="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("ok",False))' "$tmp/plan.json")"
  plan_reason="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("reason",""))' "$tmp/plan.json")"
  echo "sfx-beats: comedy plan ok=$plan_ok ($plan_reason)" >&2
  if [[ "$plan_ok" != "True" ]]; then
    passthrough "no comedy beats"; exit 0
  fi
else
  if [[ -z "$rms_in" || ! -f "$rms_in" ]]; then
    python3 "$here/../pick-segments/rms.py" "$input" > "$tmp/rms.json"
    rms_use="$tmp/rms.json"
  else
    rms_use="$rms_in"
  fi
  python3 "$here/plan_sfx.py" "$transcript" "$rms_use" "$dur" > "$tmp/plan.json"
  plan_ok="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("ok",False))' "$tmp/plan.json")"
  plan_reason="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("reason",""))' "$tmp/plan.json")"
  echo "sfx-beats: plan ok=$plan_ok ($plan_reason)" >&2
fi

python3 "$here/make_sfx.py" "$tmp/sfx.wav" "$dur" 44100 "$tmp/plan.json"

staging="$tmp/$(basename "$out")"

if [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    -i "$input" -i "$tmp/sfx.wav" \
    -filter_complex "[0:a][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.97[a]" \
    -map 0:v -map "[a]" \
    -c:v copy -c:a aac -b:a 192k -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    -i "$input" -i "$tmp/sfx.wav" \
    -map 0:v -map 1:a -shortest \
    -c:v copy -c:a aac -b:a 192k -movflags +faststart "$staging"
fi

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "sfx-beats: wrote $out  dur=${dur}s mode=$mode" >&2
echo "$out"
