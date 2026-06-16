#!/usr/bin/env bash
# jump-cut: manufacture "multi-cam" hard cuts on static talking-head stretches
# by alternating a base framing with tighter punch-in reframings of the SAME
# speaker, each cut landing on a word start. Timeline-preserving (audio copied
# untouched, total duration identical) so every downstream timestamp stays
# valid. Deterministic — no Claude. Runs on the clean 1080x1920 vertical BEFORE
# b-roll and captions, so cutaways override their own windows and captions burn
# on top. JUMP_CUT=0 disables (passthrough).
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"

input="${1:-}"
transcript="${2:-}"
out="${3:-}"
seg="${4:-${JUMP_CUT_SEG:-3.2}}"

if [[ -z "$input" || -z "$transcript" || -z "$out" ]]; then
  echo "usage: jump-cut.sh <in.mp4> <transcript.json> <out.mp4> [seg_secs=3.2]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "jump-cut: input not found: $input" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
sig="$(mtime "$input")|$([[ -f "$transcript" ]] && mtime "$transcript" || echo 0)|$seg|${JUMP_CUT:-1}|v1"
meta="$out.jcmeta"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "jump-cut: cache hit at $out" >&2
  echo "$out"; exit 0
fi
mkdir -p "$(dirname "$out")"

passthrough() {
  ffmpeg -y -hide_banner -loglevel error -i "$input" -c copy "$out" 2>/dev/null || cp "$input" "$out"
  printf '%s' "$sig" > "$meta"
  echo "$out"
}

if [[ "${JUMP_CUT:-1}" == "0" ]]; then
  echo "jump-cut: disabled (JUMP_CUT=0) — passthrough" >&2
  passthrough; exit 0
fi

dur="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$input")"
[[ -n "$dur" ]] || { echo "jump-cut: could not read duration — passthrough" >&2; passthrough; exit 0; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

JUMP_CUT_SEG="$seg" python3 "$here/plan.py" "$transcript" "$dur" > "$tmp/plan.json" 2>/dev/null \
  || { echo "jump-cut: plan failed — passthrough" >&2; passthrough; exit 0; }

flt="$(python3 - "$tmp/plan.json" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
segs, punch = p.get("segs", []), p.get("punch", [])
if not segs:
    print(""); sys.exit(0)
W, H = 1080, 1920


def even(v):
    return max(2, int(v) // 2 * 2)


def crop(level):
    if level == 0:
        return f"scale={W}:{H},setsar=1"
    s, xf, yf = punch[level - 1]
    cw, ch = even(W / s), even(H / s)
    cx = even(min(max((W - cw) * xf, 0), W - cw))
    cy = even(min(max((H - ch) * yf, 0), H - ch))
    return f"crop={cw}:{ch}:{cx}:{cy},scale={W}:{H},setsar=1"


n = len(segs)
g = f"[0:v]split={n}" + "".join(f"[v{i}]" for i in range(n)) + ";"
labels = ""
for i, s in enumerate(segs):
    g += (f"[v{i}]trim={s['t0']:.3f}:{s['t1']:.3f},setpts=PTS-STARTPTS,"
          f"{crop(s['level'])}[s{i}];")
    labels += f"[s{i}]"
g += f"{labels}concat=n={n}:v=1:a=0[vout]"
print(g)
PY
)"

if [[ -z "$flt" ]]; then
  echo "jump-cut: no cut points (short/quiet clip) — passthrough" >&2
  passthrough; exit 0
fi

ncuts="$(python3 -c 'import json,sys; print(max(0,len(json.load(open(sys.argv[1]))["segs"])-1))' "$tmp/plan.json")"
has_audio="$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$input" 2>/dev/null | head -1)"

declare -a venc dec thr amap
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do dec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do thr+=("$a"); done < <(vt_threads)
amap=(-map 0:a -c:a copy)
[[ -z "$has_audio" ]] && amap=()

if ! ffmpeg -y -hide_banner -loglevel error \
  "${dec[@]+"${dec[@]}"}" -i "$input" \
  -filter_complex "$flt" -map "[vout]" "${amap[@]}" \
  "${venc[@]}" "${thr[@]}" -movflags +faststart \
  "$out" 2>"$tmp/err.log"; then
  echo "jump-cut: ffmpeg failed — passthrough" >&2
  cat "$tmp/err.log" >&2
  passthrough; exit 0
fi

printf '%s' "$sig" > "$meta"
echo "jump-cut: wrote $out ($ncuts reframe cut(s))" >&2
echo "$out"
