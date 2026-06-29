#!/usr/bin/env bash
# like-subscribe-overlay: overlay a JS-rendered like/subscribe CTA animation
# (assets/cta.mov — ProRes 4444 with alpha, built from cta.html by build-cta.sh;
# features the channel gem avatar + @C0BALT_CUT handle) for `dur` seconds
# starting at `pos` fraction of the clip (default 0.15). The start is clamped
# so the whole CTA lands WITHIN THE FIRST THIRD of the clip — early enough
# that viewers who bail never miss it — while staying clear of the ~2.5s
# title card. The asset is time-stretched (setpts) to fit dur and pinned to
# the lower third. No SFX — the CTA overlays silently and the clip audio
# passes through untouched (the old bell ding is retired).
set -euo pipefail

input="${1:-}"
out="${2:-}"
dur="${3:-4.0}"
pos="${4:-0.15}"

if [[ -z "$input" || -z "$out" ]]; then
  echo "usage: like-subscribe-overlay.sh <input> <out> [dur=4.0] [pos=0.30]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "like-subscribe-overlay: input not found: $input" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
. "$here/../_lib/encode.sh"
declare -a venc vthr
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)
asset="$here/assets/cta.mov"
if [[ ! -f "$asset" ]]; then
  echo "like-subscribe-overlay: missing $asset — building..." >&2
  bash "$here/build-cta.sh" >&2 || {
    echo "like-subscribe-overlay: build-cta.sh failed" >&2; exit 1; }
fi

meta="$out.lsmeta"
sig="$dur|$pos|mov-v5-first-third-nosfx|vt"

if [[ -f "$out" && -f "$meta" ]]; then
  o="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  i="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  a="$(stat -f %m "$asset" 2>/dev/null || stat -c %Y "$asset")"
  newest_dep="$i"
  [[ "$a" -gt "$newest_dep" ]] && newest_dep="$a"
  if [[ "$o" -ge "$newest_dep" && "$(cat "$meta")" == "$sig" ]]; then
    echo "like-subscribe-overlay: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

read -r w h < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height -of default=nw=1:nk=1 "$input" | paste -sd' ' -)
[[ "$w" =~ ^[0-9]+$ && "$h" =~ ^[0-9]+$ ]] || {
  echo "like-subscribe-overlay: could not read video dimensions" >&2; exit 1; }

vdur="$(ffprobe -v error -select_streams v:0 -show_entries format=duration \
  -of default=nw=1:nk=1 "$input")"
[[ -n "$vdur" ]] || { echo "like-subscribe-overlay: could not read duration" >&2; exit 1; }

adur="$(ffprobe -v error -select_streams v:0 -show_entries format=duration \
  -of default=nw=1:nk=1 "$asset")"
[[ -n "$adur" ]] || adur="3.0"

# clamp dur so it fits the clip
dur="$(python3 -c "print(min(float('$dur'), max(1.5, float('$vdur') - 0.2)))")"
# start at pos fraction, clamped so the CTA ends inside the first third of the
# clip (vdur/3 - dur) and starts after the ~2.5s title card; on clips too short
# for both, the title-card floor wins, then the never-spill-past-end cap.
start="$(python3 -c "
v, d, p = float('$vdur'), float('$dur'), float('$pos')
s = min(p * v, v / 3 - d)
s = max(s, 3.0)
s = max(0.0, min(s, v - d - 0.2))
print(round(s, 4))")"
# time-stretch factor: multiply input PTS by this to fit dur seconds.
# factor < 1 => asset plays faster than its native rate.
sf="$(python3 -c "print(round(float('$dur') / float('$adur'), 6))")"
has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$input" 2>/dev/null || true)"

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# overlay sizing: full clip width (native asset is 1080x320).
# centered vertically in the bottom third (center at ~5/6 H).
cta_w="$w"
ov_y="(H*5/6)-(h/2)"

# filter chain on the asset:
#   - setpts: stretch to fit dur seconds AND offset to start = clip_dur - dur
#   - scale: width=${cta_w}, height auto (preserves aspect)
#   - format yuva: keep the prores alpha through to overlay
asset_chain="setpts=PTS*${sf}+${start}/TB,scale=${cta_w}:-2,format=yuva420p"
ov="[1:v]${asset_chain}[cta];[0:v][cta]overlay=x='(W-w)/2':y='${ov_y}':enable='between(t,${start},${start}+${dur})':format=auto[v]"

# OVERLAY_PLAN_ONLY: emit a base-relative *.overlay.json (the ProRes asset is
# already a stable on-disk file) instead of encoding. The fused compositor
# applies it with the end-card spec in one completion-cluster pass.
if [[ "${OVERLAY_PLAN_ONLY:-0}" != "0" ]]; then
  python3 - "$out" "$asset" "$asset_chain" "$ov_y" "$start" "$dur" <<'PY'
import json, sys
out, asset, chain, ov_y, start, dur = sys.argv[1:7]
spec = {
  "inputs": [{"path": asset}],
  "filter": (
    "[{L0}]%s[locta];"
    "[{IN}][locta]overlay=x='(W-w)/2':y='%s':enable='between(t,%s,%s+%s)':format=auto[{OUT}]"
    % (chain, ov_y, start, start, dur)
  ),
  "audio": None,
  "quality": "high",
}
json.dump(spec, open(out, "w"), indent=2)
PY
  printf '%s' "$sig" > "$meta"
  echo "like-subscribe-overlay: plan-only spec -> $out  start=${start}s dur=${dur}s" >&2
  echo "$out"; exit 0
fi

staging="$tmp/$(basename "$out")"

if [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    -i "$input" -i "$asset" \
    -filter_complex "${ov}" \
    -map "[v]" -map 0:a \
    "${venc[@]}" "${vthr[@]}" \
    -c:a aac -b:a 192k -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    -i "$input" -i "$asset" \
    -filter_complex "${ov}" \
    -map "[v]" \
    "${venc[@]}" "${vthr[@]}" \
    -movflags +faststart "$staging"
fi

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "like-subscribe-overlay: wrote $out  dur=${dur}s  start=${start}s  asset=${adur}s @ speed ${sf}x" >&2
echo "$out"
