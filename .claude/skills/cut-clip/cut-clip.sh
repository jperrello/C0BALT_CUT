#!/usr/bin/env bash
# cut-clip: trim a video to [t0, t1] with ffmpeg
set -euo pipefail

input="${1:-}"
t0="${2:-}"
t1="${3:-}"
out="${4:-}"
reencode="${5:-false}"

if [[ -z "$input" || -z "$t0" || -z "$t1" || -z "$out" ]]; then
  echo "usage: cut-clip.sh <input> <t0> <t1> <out> [reencode:true|false]" >&2
  exit 2
fi
if [[ ! -f "$input" ]]; then
  echo "cut-clip: input not found: $input" >&2
  exit 2
fi

awk "BEGIN{ exit !($t1 > $t0) }" || {
  echo "cut-clip: t1 ($t1) must be > t0 ($t0)" >&2; exit 2;
}

if [[ -f "$out" ]]; then
  in_mtime="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  out_mtime="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$out_mtime" -ge "$in_mtime" ]]; then
    echo "cut-clip: cache hit at $out" >&2
    exit 0
  fi
fi

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
staging="$tmp/$(basename "$out")"

if [[ "$reencode" == "true" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    -i "$input" -ss "$t0" -to "$t1" \
    -c:v libx264 -preset veryfast -crf 18 -c:a aac \
    -movflags +faststart \
    "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    -ss "$t0" -to "$t1" -i "$input" \
    -c copy -avoid_negative_ts make_zero \
    -movflags +faststart \
    "$staging"
fi

mv "$staging" "$out"
echo "cut-clip: wrote $out" >&2
