#!/usr/bin/env bash
# Shared ffmpeg encoder args. Default = VideoToolbox (Mac HW accel); fall back
# to libx264 when SHORTS_ENCODER=x264 or VideoToolbox is unavailable.
#
# Source this file then call `vt_args` / `vt_decode_args` / `vt_threads` to
# splice into a ffmpeg invocation.
#
# Tunables (env):
#   SHORTS_ENCODER   = videotoolbox|x264   (default: videotoolbox)
#   SHORTS_VBITRATE  = video bitrate for VT mode    (default: 8M)
#   SHORTS_X264_CRF  = crf for x264 fallback        (default: 20)
#   SHORTS_X264_PRESET = preset for x264 fallback   (default: veryfast)
#   SHORTS_THREADS   = -threads value               (default: 8)

_shorts_have_vt() {
  ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_videotoolbox
}

_shorts_encoder() {
  if [[ "${SHORTS_ENCODER:-videotoolbox}" == "videotoolbox" ]] && _shorts_have_vt; then
    echo videotoolbox
  else
    echo x264
  fi
}

# Video encoder args. Optional arg $1 = quality hint:
#   high  -> final-stage quality (slightly higher bitrate)
#   mid   -> default
#   low   -> intermediate stage (smaller bitrate; safe because downstream re-encodes)
vt_args() {
  local q="${1:-mid}"
  local enc; enc="$(_shorts_encoder)"
  local vb_high="${SHORTS_VBITRATE_HIGH:-10M}"
  local vb_mid="${SHORTS_VBITRATE:-8M}"
  local vb_low="${SHORTS_VBITRATE_LOW:-6M}"
  local crf_high="${SHORTS_X264_CRF_HIGH:-18}"
  local crf_mid="${SHORTS_X264_CRF:-20}"
  local crf_low="${SHORTS_X264_CRF_LOW:-22}"
  if [[ "$enc" == "videotoolbox" ]]; then
    local b
    case "$q" in high) b="$vb_high";; low) b="$vb_low";; *) b="$vb_mid";; esac
    printf '%s\0' -c:v h264_videotoolbox -b:v "$b" -allow_sw 1 -realtime 0 -tag:v avc1 -pix_fmt yuv420p
  else
    local crf
    case "$q" in high) crf="$crf_high";; low) crf="$crf_low";; *) crf="$crf_mid";; esac
    printf '%s\0' -c:v libx264 -preset "${SHORTS_X264_PRESET:-veryfast}" -crf "$crf" -pix_fmt yuv420p
  fi
}

# Decode-side hwaccel. `auto` picks VT for h264/hevc/prores and falls back to
# software for codecs VT can't decode (e.g. AV1, VP9). Splice BEFORE -i.
vt_decode_args() {
  if [[ "$(_shorts_encoder)" == "videotoolbox" ]]; then
    printf '%s\0' -hwaccel auto
  fi
}

# Thread cap to avoid context-switch thrash on high-core Macs (NETINT talk).
vt_threads() {
  printf '%s\0' -threads "${SHORTS_THREADS:-8}"
}

# Helper: read NUL-delimited tokens from a vt_* function into a bash array.
# Usage:
#   declare -a venc; while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args mid)
