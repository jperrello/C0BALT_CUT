#!/usr/bin/env bash
# title-transition: overlay an animated title card on the first seconds of a clip.
# the card slides in from the left, holds centered, slides out the right, with a
# synthesized whoosh. text is a PIL PNG (no drawtext here) moved by an overlay
# x-expression; the whoosh is a pure-python WAV mixed over the source audio.
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
python3 "$here/make_sfx.py" "$tmp/sfx.wav" "$dur" "$fly"

# ease-out cubic on the slide-in, ease-in cubic on the slide-out.
x="if(lt(t,${fly}),-w+((W-w)/2+w)*(1-pow(1-t/${fly},3)),if(lt(t,${hold_end}),(W-w)/2,(W-w)/2+(W-(W-w)/2)*pow((t-${hold_end})/${fly},3)))"
ov="[0:v][1:v]overlay=x='${x}':y='(H-h)/2':enable='between(t,0,${dur})':format=auto[v]"

staging="$tmp/$(basename "$out")"

# the title PNG is a single still frame; overlay's repeatlast holds it for the
# whole clip. (no -loop 1 — an infinite image input hangs ffmpeg here.)
if [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    -i "$input" -i "$tmp/title.png" -i "$tmp/sfx.wav" \
    -filter_complex "${ov};[2:a]apad[sfx];[0:a][sfx]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]" \
    -map "[v]" -map "[a]" \
    -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    -i "$input" -i "$tmp/title.png" -i "$tmp/sfx.wav" \
    -filter_complex "${ov};[2:a]apad[a]" \
    -map "[v]" -map "[a]" -shortest \
    -c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -movflags +faststart "$staging"
fi

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "title-transition: wrote $out  ${w}x${h}  dur=${dur}s  title=\"$title\"" >&2
echo "$out"
