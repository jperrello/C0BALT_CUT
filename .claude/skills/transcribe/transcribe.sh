#!/usr/bin/env bash
# transcribe: media file -> transcript.json with word-level timestamps
set -euo pipefail

input="${1:-}"
out="${2:-}"
lang="${3:-en}"

if [[ -z "$input" ]]; then
  echo "usage: transcribe.sh <input> [out.json] [lang]" >&2
  exit 2
fi
if [[ ! -f "$input" ]]; then
  echo "transcribe: input not found: $input" >&2
  exit 2
fi
if [[ -z "$out" ]]; then
  out="${input%.*}.transcript.json"
fi

here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."
if [[ -f "$root/.env" ]]; then
  set -a; . "$root/.env"; set +a
elif [[ -f "$root/.env.example" ]]; then
  set -a; . "$root/.env.example"; set +a
fi
: "${WHISPER_BIN:?WHISPER_BIN not set}"
: "${WHISPER_MODEL:?WHISPER_MODEL not set}"

if [[ -f "$out" ]]; then
  in_mtime="$(stat -f %m "$input" 2>/dev/null || stat -c %Y "$input")"
  out_mtime="$(stat -f %m "$out" 2>/dev/null || stat -c %Y "$out")"
  if [[ "$out_mtime" -ge "$in_mtime" ]]; then
    echo "transcribe: cache hit at $out" >&2
    exit 0
  fi
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

wav="$tmp/audio.wav"
ffmpeg -nostdin -hide_banner -loglevel error -y -i "$input" -ac 1 -ar 16000 -f wav "$wav"

base="$tmp/words"
wt="${SHORTS_WHISPER_THREADS:-$(( $(sysctl -n hw.logicalcpu 2>/dev/null || echo 8) / 2 ))}"
(( wt < 1 )) && wt=1
"$WHISPER_BIN" \
  --threads "$wt" \
  --model "$WHISPER_MODEL" \
  --language "$lang" \
  --output-json-full \
  --no-prints \
  --max-len 1 \
  --split-on-word \
  --output-file "$base" \
  "$wav" >&2

raw="$base.json"
if [[ ! -f "$raw" ]]; then
  echo "transcribe: whisper-cli produced no JSON at $raw" >&2
  exit 1
fi

python3 - "$input" "$lang" "$raw" "$out" <<'PY'
import json, re, sys

src, lang, raw_path, out_path = sys.argv[1:5]
with open(raw_path) as f:
    raw = json.load(f)

words = []
for seg in raw.get("transcription", []):
    text = (seg.get("text") or "").strip()
    if not text:
        continue
    off = seg.get("offsets") or {}
    t0 = off.get("from", 0) / 1000.0
    t1 = off.get("to", 0) / 1000.0
    words.append({"t0": round(t0, 3), "t1": round(t1, 3), "w": text})

segments = []
cur = []
def flush():
    if not cur: return
    segments.append({
        "t0": cur[0]["t0"],
        "t1": cur[-1]["t1"],
        "text": " ".join(w["w"] for w in cur).strip(),
    })
    cur.clear()

for w in words:
    cur.append(w)
    if re.search(r'[.!?]"?$', w["w"]) or len(cur) >= 18:
        flush()
flush()

with open(out_path, "w") as f:
    json.dump({
        "source": src,
        "language": lang,
        "words": words,
        "segments": segments,
    }, f, indent=2)

print(f"transcribe: wrote {out_path}  words={len(words)}  segments={len(segments)}", file=sys.stderr)
PY

echo "$out"
