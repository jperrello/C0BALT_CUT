#!/usr/bin/env bash
# broll-composite: pure ffmpeg overlay of broll_plan.json picks into the
# bottom blurred bar of a finished (loudnorm) clip. No Claude calls.
set -uo pipefail

input="${1:-}"
plan="${2:-}"
out="${3:-}"

if [[ -z "$input" || -z "$plan" || -z "$out" ]]; then
  echo "usage: broll-composite.sh <input> <broll_plan.json> <out>" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "broll-composite: input not found: $input" >&2; exit 2; }
[[ -f "$plan" ]] || { echo "broll-composite: plan not found: $plan" >&2; exit 2; }

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
in_m="$(mtime "$input")"
pl_m="$(mtime "$plan")"

meta="$out.compmeta"
sig="$in_m|$pl_m|v1"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  o_m="$(mtime "$out")"
  if [[ "$o_m" -ge "$in_m" && "$o_m" -ge "$pl_m" ]]; then
    echo "broll-composite: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

dur="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$input")"
[[ -n "$dur" ]] || { echo "broll-composite: could not read duration" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

passthrough() {
  cp "$input" "$out"
  printf '%s' "$sig" > "$meta"
  echo "broll-composite: $1 — passthrough $out" >&2
  echo "$out"; exit 0
}

npicks="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("picks", [])))' "$plan")"
[[ "$npicks" -gt 0 ]] || passthrough "empty plan"

# Build filter graph. Layout same as legacy broll: bottom bar 1080x520 at y=1332.
args=(-y -hide_banner -loglevel error -i "$input")
filter=""
last="[0:v]"
i=0
while IFS=$'\t' read -r path t0 t1; do
  [[ -f "$path" ]] || { echo "broll-composite: missing clip $path — skipping" >&2; continue; }
  args+=(-i "$path")
  idx=$((i + 1))
  d="$(python3 -c "print($t1 - $t0)")"
  end="$t1"
  filter+="[${idx}:v]trim=0:$d,setpts=PTS-STARTPTS,scale=1080:520:force_original_aspect_ratio=decrease,pad=1080:520:(ow-iw)/2:(oh-ih)/2:color=black,setpts=PTS+$t0/TB[b$i];"
  filter+="${last}[b$i]overlay=x=0:y=1332:enable='between(t,$t0,$end)'[v$i];"
  last="[v$i]"
  i=$((i + 1))
done < <(python3 -c '
import json, sys
for p in json.load(open(sys.argv[1])).get("picks", []):
    print(p["clip_path"], p["t0"], p["t1"], sep="\t")' "$plan")

[[ "$i" -gt 0 ]] || passthrough "no overlay-able picks"

mkdir -p "$(dirname "$out")"
staging="$tmp/$(basename "$out")"

ffmpeg "${args[@]}" -filter_complex "$filter" \
  -map "$last" -map 0:a? -t "$dur" \
  -c:v libx264 -preset veryfast -crf 19 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart "$staging" 2>"$tmp/ffmpeg.err" || {
    echo "broll-composite: ffmpeg failed" >&2
    cat "$tmp/ffmpeg.err" >&2
    passthrough "ffmpeg error"
  }

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "broll-composite: wrote $out  overlays=$i" >&2
echo "$out"
