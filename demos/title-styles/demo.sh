#!/usr/bin/env bash
# render one demo mp4 per title-transition style prototype, plus a combined reel.
# usage: demo.sh [base_clip] [seconds]
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
base="${1:-$root/work/11d15aee38/clip_01.sub.mp4}"
len="${2:-7}"
out="$here/out"
fps=30
mkdir -p "$out"

[[ -f "$base" ]] || { echo "demo: base clip not found: $base" >&2; exit 2; }
read -r W H < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height -of default=nw=1:nk=1 "$base" | paste -sd' ' -)

title_for() {
  case "$1" in
    slam)       echo "WE BROKE INTO MRBEAST'S STUDIO" ;;
    typewriter) echo "THE CASE NOBODY COULD SOLVE" ;;
    glitch)     echo "AI JUST CHANGED EVERYTHING" ;;
    bounce)     echo "HIS DRIVE THRU NIGHTMARE" ;;
    news)       echo "MRBEAST BUILT A WHOLE CITY" ;;
    cinematic)  echo "THE PRICE OF GENIUS" ;;
  esac
}

dur_for() {
  case "$1" in
    slam) echo 2.2 ;; typewriter) echo 3.0 ;; glitch) echo 2.4 ;;
    bounce) echo 2.4 ;; news) echo 2.8 ;; cinematic) echo 3.2 ;;
  esac
}

label_for() {
  case "$1" in
    slam)       echo "1/6 SLAM - HYPE" ;;
    typewriter) echo "2/6 TYPEWRITER - TRUE CRIME" ;;
    glitch)     echo "3/6 GLITCH - TECH" ;;
    bounce)     echo "4/6 BOUNCE - COMEDY" ;;
    news)       echo "5/6 NEWS BAR - COMMENTARY" ;;
    cinematic)  echo "6/6 CINEMATIC - DOCUMENTARY" ;;
  esac
}

bg_for() {
  local dur="$2"
  case "$1" in
    slam)
      echo "pad=iw+32:ih+32:16:16:color=black,crop=iw-32:ih-32:'16+if(between(t,0.26,0.44),14*sin(62*PI*(t-0.26))*(1-(t-0.26)/0.18),0)':'16+if(between(t,0.26,0.44),8*cos(86*PI*(t-0.26))*(1-(t-0.26)/0.18),0)',eq=brightness='if(between(t,0.26,0.36),0.5*(1-(t-0.26)/0.10),0)':eval=frame" ;;
    typewriter)
      echo "eq=brightness='-0.07*min(t/0.2\,1)*(1-min(max((t-(${dur}-0.25))/0.25\,0)\,1))':eval=frame" ;;
    cinematic)
      echo "eq=brightness='-0.10*min(t/0.5\,1)*(1-min(max((t-(${dur}-0.45))/0.45\,0)\,1))':eval=frame" ;;
    *)
      echo "null" ;;
  esac
}

styles=(slam typewriter glitch bounce news cinematic)
i=0
files=()
for s in "${styles[@]}"; do
  i=$((i+1))
  dur="$(dur_for "$s")"
  tmp="$(mktemp -d)"
  echo "== [$i/6] $s: rendering frames + sfx" >&2
  python3 "$here/styles.py" "$s" "$(title_for "$s")" "$tmp" "$W" "$H" "$dur" "$fps" "$(label_for "$s")"
  python3 "$here/sfx.py" "$tmp/events.json" "$tmp/sfx.wav"
  dst="$out/0${i}_${s}.mp4"
  ffmpeg -y -hide_banner -loglevel error \
    -i "$base" -framerate "$fps" -i "$tmp/f_%04d.png" -i "$tmp/sfx.wav" -i "$tmp/label.png" \
    -filter_complex "[0:v]$(bg_for "$s" "$dur")[bg];[bg][1:v]overlay=0:0:eof_action=pass:format=auto[tv];[tv][3:v]overlay=24:140[v];[0:a][2:a]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.85:level=false[a]" \
    -map "[v]" -map "[a]" -t "$len" -r "$fps" \
    -c:v libx264 -preset veryfast -crf 19 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -movflags +faststart "$dst"
  rm -rf "$tmp"
  files+=("$dst")
  echo "== wrote $dst" >&2
done

echo "== building reel" >&2
inputs=()
fc=""
for k in "${!files[@]}"; do
  inputs+=(-i "${files[$k]}")
  fc+="[${k}:v][${k}:a]"
done
fc+="concat=n=${#files[@]}:v=1:a=1[v][a]"
ffmpeg -y -hide_banner -loglevel error "${inputs[@]}" \
  -filter_complex "$fc" -map "[v]" -map "[a]" \
  -c:v libx264 -preset veryfast -crf 19 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart "$out/00_ALL_STYLES_REEL.mp4"

echo "demo: done — open $out" >&2
ls "$out"
