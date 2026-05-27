#!/usr/bin/env bash
# sfx-beats: mix synthesized riser/hit/stinger SFX into a clip at tension peaks.
# placement comes from transcript pivot words + per-second RMS energy.
set -euo pipefail

input="${1:-}"
transcript="${2:-}"
out="${3:-}"
rms_in="${4:-}"

if [[ -z "$input" || -z "$transcript" || -z "$out" ]]; then
  echo "usage: sfx-beats.sh <input> <transcript.json> <out> [audio_rms.json]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "sfx-beats: input not found: $input" >&2; exit 2; }
[[ -f "$transcript" ]] || { echo "sfx-beats: transcript not found: $transcript" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
meta="$out.sfxmeta"
in_mtime="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
tx_mtime="$(stat -f %m "$transcript" 2>/dev/null || stat -c %Y "$transcript")"
sig="$in_mtime|$tx_mtime"

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

python3 "$here/make_sfx.py" "$tmp/sfx.wav" "$dur" 44100 "$tmp/plan.json"

mkdir -p "$(dirname "$out")"
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
echo "sfx-beats: wrote $out  dur=${dur}s" >&2
echo "$out"
