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

heatmap_write() {
  # $1: file with two lines of %(heatmap)j / %(chapters)j output ("NA" when absent)
  python3 - "$1" "$dir/heatmap.json" <<'PY' || true
import json, sys
lines = open(sys.argv[1]).read().splitlines() + ["", ""]
def grab(line):
    try:
        v = json.loads(line)
        return v if isinstance(v, list) else []
    except Exception:
        return []
hm, ch = grab(lines[0]), grab(lines[1])
if not hm and not ch:
    sys.exit(0)
json.dump({"heatmap": hm, "chapters": ch}, open(sys.argv[2], "w"))
print(f"ingest: heatmap.json ({len(hm)} replay points, {len(ch)} chapters)", file=sys.stderr)
PY
}

if [[ -f "$out" && -f "$meta" ]]; then
  if grep -q "\"url\": \"$url\"" "$meta" 2>/dev/null; then
    echo "ingest: cache hit at $out" >&2
    # backfill the replay heatmap for sources ingested before it was captured
    if [[ ! -f "$dir/heatmap.json" ]]; then
      yt-dlp --skip-download --print "%(heatmap)j" --print "%(chapters)j" "$url" \
        > "$dir/.heatmap.raw" 2>/dev/null || true
      heatmap_write "$dir/.heatmap.raw"
      rm -f "$dir/.heatmap.raw"
    fi
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
  --print-to-file "%(heatmap)j" "$dir/.heatmap.raw" \
  --print-to-file "%(chapters)j" "$dir/.chapters.raw" \
  --no-progress \
  "$url" >&2

# most-replayed heatmap + chapters -> heatmap.json (crowd-sourced engagement
# prior for pick-segments; absent on low-view sources)
if [[ -f "$dir/.heatmap.raw" ]]; then
  cat "$dir/.heatmap.raw" "$dir/.chapters.raw" 2>/dev/null > "$dir/.hm.two" || true
  heatmap_write "$dir/.hm.two"
  rm -f "$dir/.hm.two"
fi

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

rm -f "$probe_file" "$dir/.title.txt" "$dir/.heatmap.raw" "$dir/.chapters.raw"
