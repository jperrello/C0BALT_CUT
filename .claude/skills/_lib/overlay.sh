#!/usr/bin/env bash
# Shared overlay compositor. Chains N `*.overlay.json` specs (each emitted by an
# overlay skill in OVERLAY_PLAN_ONLY mode) into ONE ffmpeg overlay pass — the
# generalization of brand-overlays' two-PNG single pass (shorts-6sp). Six
# overlay-only re-encodes collapse into two fused compositor passes (one per
# captions/completion cluster), same delivered pixels, one decode + one encode.
#
# Usage (source this file, then):
#   compose_overlays <base.mp4> <out.mp4> <quality:mid|high> <spec.json> [spec.json ...]
#
# Each *.overlay.json is base-relative and self-contained:
#   { "inputs": [ {"path":"…/sub_%06d.png","framerate":30}        # PNG sequence
#               | {"path":"…/credit.png","loop":true,"t":12.3}    # single looped PNG
#               | {"path":"…/cta.mov"} ],                          # ProRes w/ alpha
#     "filter": "[{IN}][{L0}]overlay=…[{OUT}]",   # tokens: {IN} {L0..Ln} {OUT}
#     "audio":  {"mix":"…/sfx.wav","apad":true} | null,
#     "quality": "mid"|"high" }
#
# Filter tokens (substituted by the compositor as it chains specs):
#   {IN}   incoming video label — `0:v` for the first spec, the prior spec's
#          {OUT} for the rest.
#   {L0}…  this spec's own layer inputs, in `inputs` order, mapped to global
#          ffmpeg `-i` indices.
#   {OUT}  this spec's output video label.
# The last spec's {OUT} is mapped to the encode; intermediate {OUT}s chain.
#
# Audio folding: every spec carrying an `audio.mix` adds that wav as an amix
# input over the base audio (normalize=0, then a limiter). With no audio mixes
# the base audio is stream-copied (-c:a copy) — same as the per-skill paths.
#
# bash 3.2 safe: no associative arrays, no wait -n.

# Guard against double-source.
[[ -n "${_SHORTS_OVERLAY_SH:-}" ]] && return 0
_SHORTS_OVERLAY_SH=1

# shellcheck source=/dev/null
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/encode.sh"

compose_overlays() {
  local base="$1" out="$2" quality="${3:-mid}"
  shift 3
  local -a specs=("$@")

  if [[ -z "$base" || -z "$out" || ${#specs[@]} -eq 0 ]]; then
    echo "compose_overlays: usage: compose_overlays <base> <out> <quality> <spec.json...>" >&2
    return 2
  fi
  [[ -f "$base" ]] || { echo "compose_overlays: base not found: $base" >&2; return 2; }
  local s
  for s in "${specs[@]}"; do
    [[ -f "$s" ]] || { echo "compose_overlays: spec not found: $s" >&2; return 2; }
  done

  local has_audio
  has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
    -of default=nw=1:nk=1 "$base" 2>/dev/null || true)"

  # A small python helper builds the ffmpeg input args + the full filtergraph
  # from the spec set. It emits a NUL-delimited token stream:
  #   <input-arg>\0 …  then a literal "--FILTER--"\0  then <filtergraph>\0
  #   then "--AUDIO--"\0 then (the audio-filter string OR empty)\0
  # so the bash side can read it into arrays without re-quoting hazards.
  local helper
  helper="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/overlay_build.py"

  local -a ffin=()
  local fg="" afilter="" sawdelim=0 section="in"
  while IFS= read -r -d '' tok; do
    case "$section" in
      in)
        if [[ "$tok" == "--FILTER--" ]]; then section="filter"; continue; fi
        ffin+=("$tok")
        ;;
      filter)
        if [[ "$tok" == "--AUDIO--" ]]; then section="audio"; continue; fi
        fg="$tok"
        ;;
      audio)
        afilter="$tok"
        ;;
    esac
  done < <(python3 "$helper" "$base" "$has_audio" "${specs[@]}")

  if [[ ${#ffin[@]} -eq 0 || -z "$fg" ]]; then
    echo "compose_overlays: failed to build filtergraph" >&2
    return 1
  fi

  # Encoder args (decode hwaccel + video encode + thread cap).
  local -a venc=() vdec=() vthr=()
  while IFS= read -r -d '' a; do venc+=("$a"); done < <(vt_args "$quality")
  while IFS= read -r -d '' a; do vdec+=("$a"); done < <(vt_decode_args)
  while IFS= read -r -d '' a; do vthr+=("$a"); done < <(vt_threads)

  mkdir -p "$(dirname "$out")"
  local tmp; tmp="$(mktemp -d)"
  local staging="$tmp/$(basename "$out")"

  # Build the -map / audio-codec tail. If the spec set folded an audio mix the
  # filtergraph already emits an [a]; otherwise copy the base audio (or none).
  local -a amap=()
  if [[ -n "$afilter" ]]; then
    fg="${fg};${afilter}"
    amap=(-map "[a]" -c:a aac -b:a 192k)
  elif [[ "$has_audio" == "audio" ]]; then
    amap=(-map 0:a -c:a copy)
  fi

  if ! ffmpeg -y -hide_banner -loglevel error \
      ${vdec[@]+"${vdec[@]}"} -i "$base" \
      "${ffin[@]}" \
      -filter_complex "$fg" \
      -map "[v]" "${amap[@]+"${amap[@]}"}" \
      "${venc[@]}" "${vthr[@]}" -movflags +faststart "$staging" 2>"$tmp/err.log"; then
    echo "compose_overlays: ffmpeg failed" >&2
    cat "$tmp/err.log" >&2
    rm -rf "$tmp"
    return 1
  fi

  mv "$staging" "$out"
  rm -rf "$tmp"
  echo "compose_overlays: wrote $out (${#specs[@]} spec(s), quality=$quality)" >&2
  return 0
}
