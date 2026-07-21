#!/usr/bin/env bash
# title-transition: animate the title in the TOP banner over the LIVE opening
# footage (cold open — no blocking card), then let it clear by TITLE_SWAP so
# brand-overlays can fade the source citation into the same top slot. a PIL
# frame sequence (styles.py) with a synced glitch SFX bed (sfx.py, folded into
# the audio mix; TITLE_SFX=0 for silent) and NO full-frame bg treatment (it
# shook/dimmed the live shot).
set -euo pipefail

input="${1:-}"
title="${2:-}"
out="${3:-}"
# only one title animation now — glitch — applied to every short. the 4th arg is
# accepted for back-compat but ignored.
style="glitch"
dur="${5:-auto}"

# the title clears at TITLE_SWAP (shared with brand-overlays, which fades the
# citation in at the same second) and animates in the top-banner zone. Default
# 2.5s so that after the final speed-up step (SPEED=1.25x) the title still holds
# ~2.0s on screen (2.5 / 1.25).
swap="${TITLE_SWAP:-2.5}"
anchor="${TITLE_ANCHOR_FRAC:-0.135}"

if [[ -z "$input" || -z "$title" || -z "$out" ]]; then
  echo "usage: title-transition.sh <input> <title> <out> [ignored] [dur=auto]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "title-transition: input not found: $input" >&2; exit 2; }

# the title's full lifecycle (animate in, hold, fade out) fits inside the hold
# window so it has fully cleared the top banner by TITLE_SWAP.
if [[ "$dur" == "auto" ]]; then
  dur="$swap"
fi

here="$(cd "$(dirname "$0")" && pwd)"
meta="$out.ttmeta"
sig="$title|$style|$dur|top$anchor|sfx${TITLE_SFX:-1}|zc|g${TITLE_SFX_GAIN:-1.0}"

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

# OVERLAY_PLAN_ONLY: render the PNG sequence + (optional) SFX wav to a STABLE
# sidecar dir and emit a base-relative *.overlay.json instead of encoding. The
# fused compositor applies it with the subtitle + brand specs in one
# captions-cluster pass and folds the SFX wav into the cluster audio mix.
if [[ "${OVERLAY_PLAN_ONLY:-0}" != "0" ]]; then
  assets="${out}.assets"
  rm -rf "$assets"; mkdir -p "$assets"
  TITLE_ANCHOR_FRAC="$anchor" python3 "$here/styles.py" "$style" "$title" "$assets" "$w" "$h" "$dur" "$fps"
  sfx=""
  if [[ "${TITLE_SFX:-1}" != "0" ]] && python3 "$here/sfx.py" "$assets/sfx.wav" "$dur" "$fps" 2>/dev/null; then
    sfx="$assets/sfx.wav"
  fi
  python3 - "$out" "$assets/f_%04d.png" "$fps" "$sfx" <<'PY'
import json, os, sys
out, seqpat, fps, sfx = sys.argv[1:5]
spec = {
  "inputs": [{"path": seqpat, "framerate": float(fps)}],
  # full-frame top-banner PNG seq over the live footage; eof_action=pass so the
  # base keeps playing once the (short) title seq ends.
  "filter": "[{IN}][{L0}]overlay=0:0:eof_action=pass:format=auto[{OUT}]",
  # the glitch SFX bed the compositor folds into the cluster audio mix.
  "audio": {"mix": os.path.abspath(sfx), "apad": True} if sfx else None,
  "quality": "mid",
}
json.dump(spec, open(out, "w"), indent=2)
PY
  printf '%s' "$sig" > "$meta"
  echo "title-transition: plan-only spec -> $out  style=${style} dur=${dur}s  title=\"$title\"" >&2
  echo "$out"; exit 0
fi

mkdir -p "$(dirname "$out")"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

TITLE_ANCHOR_FRAC="$anchor" python3 "$here/styles.py" "$style" "$title" "$tmp" "$w" "$h" "$dur" "$fps"

sfx=""
if [[ "${TITLE_SFX:-1}" != "0" ]] && python3 "$here/sfx.py" "$tmp/sfx.wav" "$dur" "$fps" 2>/dev/null; then
  sfx="$tmp/sfx.wav"
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

if [[ "$has_audio" == "audio" && -n "$sfx" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    ${vdec[@]+"${vdec[@]}"} -i "$input" -framerate "$fps" -i "$tmp/f_%04d.png" -i "$sfx" \
    -filter_complex "${ov};[2:a]apad[sfx];[0:a][sfx]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.97[a]" \
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
