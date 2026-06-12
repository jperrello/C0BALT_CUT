#!/usr/bin/env bash
# title-transition: overlay an animated, SFX-backed title card on the opening
# seconds of a clip. five styles, each a PIL frame sequence (styles.py) plus a
# synthesized sfx bed (sfx.py) mixed under the clip audio with a limiter.
set -euo pipefail

input="${1:-}"
title="${2:-}"
out="${3:-}"
style="${4:-slam}"
dur="${5:-auto}"

if [[ -z "$input" || -z "$title" || -z "$out" ]]; then
  echo "usage: title-transition.sh <input> <title> <out> [style=slam] [dur=auto]" >&2
  echo "styles: slam typewriter glitch bounce cinematic" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "title-transition: input not found: $input" >&2; exit 2; }

case "$style" in
  slam|typewriter|glitch|bounce|cinematic) ;;
  *) echo "title-transition: unknown style '$style' — using slam" >&2; style=slam ;;
esac

if [[ "$dur" == "auto" ]]; then
  case "$style" in
    slam) dur=2.2 ;; typewriter) dur=3.0 ;; glitch) dur=2.4 ;;
    bounce) dur=2.4 ;; cinematic) dur=3.2 ;;
  esac
fi

here="$(cd "$(dirname "$0")" && pwd)"
meta="$out.ttmeta"
sig="$title|$style|$dur"

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

fps=30
mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 "$here/styles.py" "$style" "$title" "$tmp" "$w" "$h" "$dur" "$fps"
python3 "$here/sfx.py" "$tmp/events.json" "$tmp/sfx.wav"

# per-style background treatment, applied to the clip BEFORE the title overlay
# so the card itself never shakes/flashes/dims:
#   slam       — flash + screen shake locked to the landing frame (t=0.26)
#   typewriter — slight dim while the card is up (ramped in/out)
#   cinematic  — deeper dim, slower ramp
#   glitch/bounce — none
case "$style" in
  slam)
    bg="pad=iw+32:ih+32:16:16:color=black,crop=iw-32:ih-32:'16+if(between(t,0.26,0.44),14*sin(62*PI*(t-0.26))*(1-(t-0.26)/0.18),0)':'16+if(between(t,0.26,0.44),8*cos(86*PI*(t-0.26))*(1-(t-0.26)/0.18),0)',eq=brightness='if(between(t,0.26,0.36),0.5*(1-(t-0.26)/0.10),0)':eval=frame" ;;
  typewriter)
    bg="eq=brightness='-0.07*min(t/0.2\,1)*(1-min(max((t-(${dur}-0.25))/0.25\,0)\,1))':eval=frame" ;;
  cinematic)
    bg="eq=brightness='-0.10*min(t/0.5\,1)*(1-min(max((t-(${dur}-0.45))/0.45\,0)\,1))':eval=frame" ;;
  *)
    bg="null" ;;
esac

ov="[0:v]${bg}[bgv];[bgv][1:v]overlay=0:0:eof_action=pass:format=auto[v]"

staging="$tmp/$(basename "$out")"

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

if [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -framerate "$fps" -i "$tmp/f_%04d.png" -i "$tmp/sfx.wav" \
    -filter_complex "${ov};[0:a][2:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.85:level=false[a]" \
    -map "[v]" -map "[a]" \
    "${venc[@]}" \
    -c:a aac -b:a 192k "${vthr[@]}" -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -framerate "$fps" -i "$tmp/f_%04d.png" -i "$tmp/sfx.wav" \
    -filter_complex "${ov}" \
    -map "[v]" -map 2:a \
    "${venc[@]}" \
    -c:a aac -b:a 192k "${vthr[@]}" -shortest -movflags +faststart "$staging"
fi

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "title-transition: wrote $out  ${w}x${h}  style=${style} dur=${dur}s  title=\"$title\"" >&2
echo "$out"
