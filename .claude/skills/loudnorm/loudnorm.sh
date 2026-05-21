#!/usr/bin/env bash
# loudnorm: two-pass ffmpeg loudnorm
set -euo pipefail

input="${1:-}"
out="${2:-}"
I="${3:--14}"
TP="${4:--1.5}"
LRA="${5:-11}"

if [[ -z "$input" || -z "$out" ]]; then
  echo "usage: loudnorm.sh <input> <out> [I=-14] [TP=-1.5] [LRA=11]" >&2
  exit 2
fi
if [[ ! -f "$input" ]]; then
  echo "loudnorm: input not found: $input" >&2
  exit 2
fi

if [[ -f "$out" ]]; then
  in_mtime="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  out_mtime="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$out_mtime" -ge "$in_mtime" ]]; then
    echo "loudnorm: cache hit at $out" >&2
    exit 0
  fi
fi

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Pass 1: measure
measure_log="$tmp/measure.log"
ffmpeg -hide_banner -nostats -i "$input" \
  -af "loudnorm=I=${I}:TP=${TP}:LRA=${LRA}:print_format=json" \
  -f null - 2> "$measure_log" || {
    cat "$measure_log" >&2
    echo "loudnorm: measure pass failed" >&2
    exit 1
  }

# Extract JSON block (last {...} in stderr)
json="$(awk '/^{/{flag=1; buf=""} flag{buf=buf"\n"$0} /^}/{flag=0; print buf}' "$measure_log" | tail -n +2)"
if [[ -z "$json" ]]; then
  echo "loudnorm: could not parse measurement JSON" >&2
  cat "$measure_log" >&2
  exit 1
fi

get() { echo "$json" | python3 -c "import sys,json; print(json.load(sys.stdin)['$1'])"; }
mI=$(get input_i)
mTP=$(get input_tp)
mLRA=$(get input_lra)
mThresh=$(get input_thresh)
mOffset=$(get target_offset)

echo "loudnorm: measured I=$mI TP=$mTP LRA=$mLRA thresh=$mThresh offset=$mOffset" >&2

staging="$tmp/$(basename "$out")"
ffmpeg -y -hide_banner -loglevel error \
  -i "$input" \
  -af "loudnorm=I=${I}:TP=${TP}:LRA=${LRA}:measured_I=${mI}:measured_TP=${mTP}:measured_LRA=${mLRA}:measured_thresh=${mThresh}:offset=${mOffset}:linear=true:print_format=summary" \
  -c:v copy -c:a aac -b:a 192k \
  -movflags +faststart \
  "$staging"

mv "$staging" "$out"
echo "loudnorm: wrote $out" >&2
