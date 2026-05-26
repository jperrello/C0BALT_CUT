#!/usr/bin/env bash
# tighten-pace: collapse inter-word silences > gap_max in a clip + re-time its transcript.
# Gaps above gap_max collapse to collapse_to (or sentence_beat if the preceding word
# ends a sentence with . ? or !).
set -euo pipefail

in_clip="${1:-}"
in_tx="${2:-}"
out_clip="${3:-}"
out_tx="${4:-}"
gap_max="${5:-${TIGHTEN_GAP:-0.18}}"
sentence_beat="${6:-${TIGHTEN_SENTENCE_BEAT:-0.15}}"
collapse_to="${7:-${TIGHTEN_COLLAPSE_TO:-0.08}}"

if [[ -z "$in_clip" || -z "$in_tx" || -z "$out_clip" || -z "$out_tx" ]]; then
  echo "usage: tighten-pace.sh <in_clip> <in_tx> <out_clip> <out_tx> [gap_max=0.18] [sentence_beat=0.15] [collapse_to=0.08]" >&2
  exit 2
fi
[[ -f "$in_clip" ]] || { echo "tighten-pace: clip not found: $in_clip" >&2; exit 2; }
[[ -f "$in_tx" ]]   || { echo "tighten-pace: transcript not found: $in_tx" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
meta="$out_clip.tpmeta"
in_mtime="$(stat -f %m "$in_clip" 2>/dev/null || stat -c %Y "$in_clip")"
tx_mtime="$(stat -f %m "$in_tx"   2>/dev/null || stat -c %Y "$in_tx")"
sig="$in_mtime|$tx_mtime|$gap_max|$sentence_beat|$collapse_to"

if [[ -f "$out_clip" && -f "$out_tx" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "tighten-pace: cache hit at $out_clip" >&2
  echo "$out_clip"; exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/plan.py" "$in_tx" "$gap_max" "$sentence_beat" "$collapse_to" > "$tmp/plan.json"

n_keeps="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["keeps"]))' "$tmp/plan.json")"
removed="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["removed_total"])' "$tmp/plan.json")"

mkdir -p "$(dirname "$out_clip")" "$(dirname "$out_tx")"

if [[ "$n_keeps" -le 1 ]]; then
  echo "tighten-pace: no cuts needed (gap_max=$gap_max), copying through" >&2
  cp "$in_clip" "$out_clip"
  python3 -c '
import json,sys
plan=json.load(open(sys.argv[1]))
src=json.load(open(sys.argv[2]))
out={"source": src.get("source",""), "language": src.get("language","en"), "words": plan["words"]}
json.dump(out, open(sys.argv[3],"w"))
' "$tmp/plan.json" "$in_tx" "$out_tx"
  printf '%s' "$sig" > "$meta"
  echo "$out_clip"; exit 0
fi

expr="$(python3 -c '
import json,sys
keeps=json.load(open(sys.argv[1]))["keeps"]
print("+".join(f"between(t,{a:.4f},{b:.4f})" for a,b in keeps))
' "$tmp/plan.json")"

echo "tighten-pace: $n_keeps keep range(s), ~${removed}s collapsed (gap_max=$gap_max sentence_beat=$sentence_beat collapse_to=$collapse_to)" >&2

staging="$tmp/$(basename "$out_clip")"
ffmpeg -y -hide_banner -loglevel error \
  -i "$in_clip" \
  -vf "select='${expr}',setpts=N/FRAME_RATE/TB" \
  -af "aselect='${expr}',asetpts=N/SR/TB" \
  -c:v libx264 -preset veryfast -crf 18 -c:a aac -b:a 192k -movflags +faststart \
  "$staging"

mv "$staging" "$out_clip"

python3 -c '
import json,sys
plan=json.load(open(sys.argv[1]))
src=json.load(open(sys.argv[2]))
out={"source": src.get("source",""), "language": src.get("language","en"), "words": plan["words"]}
json.dump(out, open(sys.argv[3],"w"))
' "$tmp/plan.json" "$in_tx" "$out_tx"

printf '%s' "$sig" > "$meta"
echo "tighten-pace: wrote $out_clip" >&2
echo "$out_clip"
