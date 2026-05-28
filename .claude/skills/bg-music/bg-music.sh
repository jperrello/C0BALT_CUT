#!/usr/bin/env bash
# bg-music: mix a random looped track from ./songs/<category>/ under a clip.
set -euo pipefail

in="${1:-}"
out="${2:-}"
category="${3:-ALL SONGS}"
volume="${4:-0.17}"
fade="${5:-0.6}"

if [[ -z "$in" || -z "$out" ]]; then
  echo "usage: bg-music.sh <input> <out> [category='ALL SONGS'] [volume=0.17] [fade=0.6]" >&2
  exit 2
fi
[[ -f "$in" ]] || { echo "bg-music: input not found: $in" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"

# Build candidate list. "ALL SONGS" = recurse across every mood folder.
if [[ "$category" == "ALL SONGS" ]]; then
  search_root="$root/songs"
  depth_args=()
else
  search_root="$root/songs/$category"
  depth_args=(-maxdepth 1)
  if [[ ! -d "$search_root" ]]; then
    echo "bg-music: songs dir not found: $search_root" >&2
    echo "bg-music: available categories:" >&2
    ls "$root/songs/" 2>/dev/null | sed 's/^/  /' >&2 || true
    exit 2
  fi
fi

candidates="$(find "$search_root" ${depth_args[@]+"${depth_args[@]}"} -type f \( -iname '*.mp3' -o -iname '*.wav' -o -iname '*.m4a' \) 2>/dev/null)"
[[ -n "$candidates" ]] || { echo "bg-music: no audio files under $search_root" >&2; exit 2; }

# Recent-pick blacklist: avoid repeating the last 5 tracks across runs.
recent_file="$root/songs/.recent"
recent=""
[[ -f "$recent_file" ]] && recent="$(cat "$recent_file")"

filtered="$candidates"
if [[ -n "$recent" ]]; then
  filtered="$(printf '%s\n' "$candidates" | grep -vxF -f <(printf '%s\n' "$recent") || true)"
  [[ -z "$filtered" ]] && filtered="$candidates"  # all songs recently used; reset
fi

track="$(printf '%s\n' "$filtered" | sort -R | head -n 1)"
[[ -n "$track" && -f "$track" ]] || { echo "bg-music: pick failed" >&2; exit 2; }
track_name="$(basename "$track")"
track_mood="$(basename "$(dirname "$track")")"
echo "bg-music: picked '$track_name' from '$track_mood' (vol=$volume)" >&2

# Update recent list (keep last 5).
{ printf '%s\n' "$track"; printf '%s\n' "$recent"; } | awk 'NF && !seen[$0]++' | head -n 5 > "$recent_file"

meta="$out.bgmeta"
in_mtime="$(stat -f %m "$in" 2>/dev/null || stat -c %Y "$in")"
sig="$in_mtime|$category|$volume|$fade|$track_name"

if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "bg-music: cache hit at $out" >&2
  echo "$out"; exit 0
fi

has_audio="$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_type \
  -of default=nw=1:nk=1 "$in" 2>/dev/null || true)"

vdur="$(ffprobe -v error -select_streams v:0 -show_entries stream=duration \
  -of default=nw=1:nk=1 "$in" 2>/dev/null || true)"
[[ -n "$vdur" && "$vdur" != "N/A" ]] || \
  vdur="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$in")"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$(dirname "$out")"
staging="$tmp/$(basename "$out")"

if [[ "$has_audio" == "audio" ]]; then
  ffmpeg -y -hide_banner -loglevel error \
    -i "$in" -stream_loop -1 -i "$track" \
    -filter_complex "[0:a]apad=whole_dur=${vdur}[spk];[1:a]volume=${volume},afade=t=in:st=0:d=${fade},atrim=duration=${vdur}[bg];[spk][bg]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.97[a]" \
    -map 0:v -map "[a]" -t "$vdur" \
    -c:v copy -c:a aac -b:a 192k -movflags +faststart "$staging"
else
  ffmpeg -y -hide_banner -loglevel error \
    -i "$in" -stream_loop -1 -i "$track" \
    -filter_complex "[1:a]volume=${volume},afade=t=in:st=0:d=${fade},atrim=duration=${vdur},alimiter=limit=0.97[a]" \
    -map 0:v -map "[a]" -t "$vdur" \
    -c:v copy -c:a aac -b:a 192k -movflags +faststart "$staging"
fi

mv "$staging" "$out"
printf '%s' "$sig" > "$meta"
echo "bg-music: wrote $out" >&2
echo "$out"
