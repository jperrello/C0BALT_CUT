#!/usr/bin/env bash
# cut-filler: apply a trim-filler keeps.json to a clip's video.
set -euo pipefail

in_clip="${1:-}"
keeps="${2:-}"
out_clip="${3:-}"

if [[ -z "$in_clip" || -z "$keeps" || -z "$out_clip" ]]; then
  echo "usage: cut-filler.sh <in_clip> <keeps.json> <out_clip>" >&2
  exit 2
fi
[[ -f "$in_clip" ]] || { echo "cut-filler: clip not found: $in_clip" >&2; exit 2; }
[[ -f "$keeps" ]]   || { echo "cut-filler: keeps not found: $keeps" >&2; exit 2; }

meta="$out_clip.cfmeta"
clip_mtime="$(stat -f %m "$in_clip" 2>/dev/null || stat -c %Y "$in_clip")"
keeps_mtime="$(stat -f %m "$keeps"  2>/dev/null || stat -c %Y "$keeps")"
sig="$clip_mtime|$keeps_mtime"

if [[ -f "$out_clip" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "cut-filler: cache hit at $out_clip" >&2
  echo "$out_clip"; exit 0
fi

mkdir -p "$(dirname "$out_clip")"

n_keeps="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1])).get("keeps",[])))' "$keeps")"
removed_total="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("removed_total",0.0))' "$keeps")"

if [[ "$n_keeps" -le 0 ]]; then
  echo "cut-filler: empty keeps — copying input through" >&2
  cp "$in_clip" "$out_clip"
  printf '%s' "$sig" > "$meta"
  echo "$out_clip"; exit 0
fi

# If only one keep range and it covers ~the whole clip, just copy through.
should_copy="$(python3 -c '
import json,sys,subprocess
keeps=json.load(open(sys.argv[1]))["keeps"]
if len(keeps)!=1:
    print("0"); sys.exit(0)
dur=float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",sys.argv[2]]).strip())
a,b=keeps[0]
print("1" if a<=0.05 and (dur-b)<=0.05 else "0")
' "$keeps" "$in_clip" 2>/dev/null || echo 0)"

if [[ "$should_copy" == "1" ]]; then
  echo "cut-filler: keeps cover full clip — copying through" >&2
  cp "$in_clip" "$out_clip"
  printf '%s' "$sig" > "$meta"
  echo "$out_clip"; exit 0
fi

expr="$(python3 -c '
import json,sys
keeps=json.load(open(sys.argv[1]))["keeps"]
print("+".join(f"between(t,{a:.4f},{b:.4f})" for a,b in keeps))
' "$keeps")"

echo "cut-filler: $n_keeps keep range(s), ~${removed_total}s removed" >&2

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
staging="$tmp/$(basename "$out_clip")"

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args low)
while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

ffmpeg -y -hide_banner -loglevel error \
  ${vdec[@]+"${vdec[@]}"} -i "$in_clip" \
  -vf "select='${expr}',setpts=N/FRAME_RATE/TB" \
  -af "aselect='${expr}',asetpts=N/SR/TB" \
  "${venc[@]}" -c:a aac -b:a 192k \
  "${vthr[@]}" -movflags +faststart \
  "$staging"

mv "$staging" "$out_clip"
printf '%s' "$sig" > "$meta"
echo "cut-filler: wrote $out_clip" >&2
echo "$out_clip"
