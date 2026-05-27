#!/usr/bin/env bash
# title-transition: overlay an animated title card on the first seconds of a clip.
# the card pops in at center with a back-out (overshoot) scale, holds, then
# scales back down to nothing. impact effects (flash + shake) fire on the
# landing frame. text is a PIL PNG scaled per-frame by ffmpeg.
set -euo pipefail

input="${1:-}"
title="${2:-}"
out="${3:-}"
dur="${4:-2.5}"
font="${5:-auto}"

if [[ -z "$input" || -z "$title" || -z "$out" ]]; then
  echo "usage: title-transition.sh <input> <title> <out> [dur=2.5] [font_size=auto]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "title-transition: input not found: $input" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
meta="$out.ttmeta"
sig="$title|$dur|$font"

if [[ -f "$out" && -f "$meta" ]]; then
  o="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  i="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  if [[ "$o" -ge "$i" && "$(cat "$meta")" == "$sig" ]]; then
    echo "title-transition: cache hit at $out" >&2
    echo "$out"; exit 0
  fi
fi

read -r w h < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height -of default=nw=1:nk=1 "$input" | paste -sd' ' -)
[[ "$w" =~ ^[0-9]+$ && "$h" =~ ^[0-9]+$ ]] || {
  echo "title-transition: could not read video dimensions" >&2; exit 1; }

has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$input" 2>/dev/null || true)"

fly="$(python3 -c "print(round(min(0.45, $dur/3), 4))")"
hold_end="$(python3 -c "print(round($dur - min(0.45, $dur/3), 4))")"

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/render_title.py" "$title" "$tmp/title.png" "$w" "$h" "$font"

# scale factor S(t) — drives the per-frame scale on the title PNG.
#   pop in (t < fly):    0.3 -> ~1.07 (overshoot) -> 1.0   via back-out Penner ease
#   hold (t < hold_end): 1.0
#   pop out (t < dur):   1.0 -> 0                          via ease-in (p^1.5)
# back_out(p) = 1 + 2.70158*(p-1)^3 + 1.70158*(p-1)^2  (p = t/fly)
scale_expr="if(lt(t,${fly}),0.3+0.7*(1+2.70158*pow(t/${fly}-1,3)+1.70158*pow(t/${fly}-1,2)),if(lt(t,${hold_end}),1,if(gt(1-(t-${hold_end})/${fly},0),pow(1-(t-${hold_end})/${fly},1.5),0)))"

# impact effects locked to the landing frame (t=fly):
#   - white flash: 70ms ramp-down via eq=brightness
#   - screen shake: 150ms damped sinusoid in x and y, applied via pad+crop window
# applied to the source video BEFORE the title is overlaid, so the title itself doesn't shake/flash.
flash_end="$(python3 -c "print(round($fly + 0.07, 4))")"
shake_end="$(python3 -c "print(round($fly + 0.15, 4))")"
flash_expr="if(between(t,${fly},${flash_end}),0.38*(1-(t-${fly})/0.07),0)"
shake_x="if(between(t,${fly},${shake_end}),9*sin(60*PI*(t-${fly}))*(1-(t-${fly})/0.15),0)"
shake_y="if(between(t,${fly},${shake_end}),5*cos(80*PI*(t-${fly}))*(1-(t-${fly})/0.15),0)"

# scale=eval=frame requires a multi-frame input. -loop 1 -t ${dur} on the PNG gives a bounded looped stream.
# overlay is centered at every frame on the (now time-varying) scaled title dims.
ov="[0:v]pad=iw+24:ih+24:12:12:color=black,crop=iw-24:ih-24:'12+${shake_x}':'12+${shake_y}',eq=brightness='${flash_expr}'[base];[1:v]scale=w='iw*(${scale_expr})':h='ih*(${scale_expr})':eval=frame:flags=bicubic[ttl];[base][ttl]overlay=x='(W-w)/2':y='(H-h)/2':enable='between(t,0,${dur})':format=auto[v]"

staging="$tmp/$(basename "$out")"

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

# the title PNG is looped as a bounded video stream (-loop 1 -t ${dur}) so
# scale=eval=frame can re-evaluate the scale expression per frame.
if [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -loop 1 -t "$dur" -i "$tmp/title.png" \
    -filter_complex "${ov}" \
    -map "[v]" -map 0:a \
    "${venc[@]}" \
    -c:a aac -b:a 192k "${vthr[@]}" -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -loop 1 -t "$dur" -i "$tmp/title.png" \
    -filter_complex "${ov}" \
    -map "[v]" \
    "${venc[@]}" \
    "${vthr[@]}" -movflags +faststart "$staging"
fi

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "title-transition: wrote $out  ${w}x${h}  dur=${dur}s  title=\"$title\"" >&2
echo "$out"
