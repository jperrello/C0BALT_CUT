#!/usr/bin/env bash
# ingest: URL -> work/<id>/source.mp4 + ingest.json
set -euo pipefail

url="${1:-}"
id="${2:-}"
workroot="${WORKDIR:-./work}"

if [[ -z "$url" ]]; then
  echo "usage: ingest.sh <url> [id]" >&2
  exit 2
fi

if [[ -z "$id" ]]; then
  id="$(printf '%s' "$url" | shasum | cut -c1-10)"
fi

dir="$workroot/$id"
mkdir -p "$dir"
out="$dir/source.mp4"
meta="$dir/ingest.json"

if [[ -f "$out" && -f "$meta" ]]; then
  if grep -q "\"url\": \"$url\"" "$meta" 2>/dev/null; then
    echo "ingest: cache hit at $out" >&2
    cat "$meta"
    exit 0
  fi
fi

# --embed-metadata writes the title into the mp4 container; --print-to-file
# also drops the raw title alongside, since merged-mp4 tags are unreliable.
yt-dlp -f 'bv*+ba/b' --merge-output-format mp4 \
  -o "$dir/source.%(ext)s" \
  --embed-metadata \
  --print-to-file "%(title)s" "$dir/.title.txt" \
  --no-progress \
  "$url" >&2

if [[ ! -f "$out" ]]; then
  # yt-dlp may have written a different ext, find and rename
  cand="$(ls "$dir"/source.* 2>/dev/null | head -n1 || true)"
  if [[ -n "$cand" && "$cand" != "$out" ]]; then
    mv "$cand" "$out"
  fi
fi

probe_file="$dir/.probe.json"
ffprobe -v error -print_format json -show_format -show_streams "$out" > "$probe_file"

python3 - "$id" "$url" "$out" "$meta" "$probe_file" "$dir/.title.txt" <<'PY'
import json, os, sys
id, url, out, meta, probe_file, title_file = sys.argv[1:7]
with open(probe_file) as f:
    probe = json.load(f)
v = next((s for s in probe["streams"] if s.get("codec_type") == "video"), {})
fps_raw = v.get("avg_frame_rate", "0/1")
num, _, den = fps_raw.partition("/")
try:
    fps = float(num) / float(den) if float(den) else 0.0
except Exception:
    fps = 0.0
title = ""
if os.path.exists(title_file):
    title = open(title_file).read().strip()
if not title:
    title = probe.get("format", {}).get("tags", {}).get("title", "")
data = {
    "id": id,
    "url": url,
    "title": title,
    "duration": float(probe.get("format", {}).get("duration", 0.0)),
    "fps": round(fps, 3),
    "width": int(v.get("width", 0)),
    "height": int(v.get("height", 0)),
    "path": out,
}
with open(meta, "w") as f:
    json.dump(data, f, indent=2)
print(json.dumps(data, indent=2))
PY

rm -f "$probe_file" "$dir/.title.txt"
