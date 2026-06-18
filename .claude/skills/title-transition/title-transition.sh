#!/usr/bin/env bash
# title-transition: animate the title in the TOP banner over the LIVE opening
# footage (cold open — no blocking card), then let it clear by TITLE_SWAP so
# brand-overlays can fade the source citation into the same top slot. five
# styles, each a PIL frame sequence (styles.py) with its OWN matched SFX bed
# (events.json -> sfx.py, mixed under the live audio; TITLE_SFX=0 disables) and
# NO full-frame bg treatment (it shook/dimmed the live shot).
set -euo pipefail

input="${1:-}"
title="${2:-}"
out="${3:-}"
style="${4:-slam}"
dur="${5:-auto}"

# the title clears at TITLE_SWAP (shared with brand-overlays, which fades the
# citation in at the same second) and animates in the top-banner zone.
swap="${TITLE_SWAP:-2.0}"
anchor="${TITLE_ANCHOR_FRAC:-0.135}"

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

# the title's full lifecycle (animate in, hold, fade out) fits inside the hold
# window so it has fully cleared the top banner by TITLE_SWAP.
if [[ "$dur" == "auto" ]]; then
  dur="$swap"
fi

here="$(cd "$(dirname "$0")" && pwd)"
meta="$out.ttmeta"
# TITLE_SFX=0 disables the style-matched animation SFX (default on).
sfx_on="${TITLE_SFX:-1}"
sig="$title|$style|$dur|top$anchor|sfx$sfx_on"

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

TITLE_ANCHOR_FRAC="$anchor" python3 "$here/styles.py" "$style" "$title" "$tmp" "$w" "$h" "$dur" "$fps"

# style-matched animation SFX: styles.py writes events.json (the per-style cue
# list — slam=riser+boom, glitch=zaps, typewriter=keys, bounce=pops, etc.);
# sfx.py synthesizes it to a wav mixed UNDER the live audio so the title's
# sound matches its animation. TITLE_SFX=0 skips it.
sfx_wav=""
if [[ "$sfx_on" != "0" && -f "$tmp/events.json" ]]; then
  if python3 "$here/sfx.py" "$tmp/events.json" "$tmp/sfx.wav" >&2; then
    sfx_wav="$tmp/sfx.wav"
  else
    echo "title-transition: sfx synth failed — continuing silent" >&2
  fi
fi

# title PNG sequence overlaid directly on the LIVE footage at the top banner —
# no full-frame bg treatment (the old flash/shake/dim shook the live shot).
# styles.py frames are full-frame, so overlay at 0:0.
ov="[0:v][1:v]overlay=0:0:eof_action=pass:format=auto[v]"

staging="$tmp/$(basename "$out")"

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/../_lib" && pwd)/encode.sh"
venc=(); vdec=(); vthr=()
while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

if [[ "$has_audio" == "audio" && -n "$sfx_wav" ]]; then
  # mix the synthesized animation SFX under the live audio (SFX starts at the
  # title animate-in, t=0); apad keeps amix from truncating to the short bed.
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -framerate "$fps" -i "$tmp/f_%04d.png" \
    -i "$sfx_wav" \
    -filter_complex "${ov};[2:a]apad[sfx];[0:a][sfx]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]" \
    -map "[v]" -map "[a]" \
    "${venc[@]}" \
    -c:a aac -b:a 192k "${vthr[@]}" -movflags +faststart "$staging"
elif [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -framerate "$fps" -i "$tmp/f_%04d.png" \
    -filter_complex "${ov}" \
    -map "[v]" -map 0:a \
    "${venc[@]}" \
    -c:a copy "${vthr[@]}" -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -framerate "$fps" -i "$tmp/f_%04d.png" \
    -filter_complex "${ov}" \
    -map "[v]" \
    "${venc[@]}" \
    "${vthr[@]}" -movflags +faststart "$staging"
fi

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "title-transition: wrote $out  ${w}x${h}  style=${style} dur=${dur}s  title=\"$title\"" >&2
echo "$out"
