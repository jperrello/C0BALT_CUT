#!/usr/bin/env python3
# Returns up to TOP 3 candidate video URLs per query, smallest landscape mp4
# with width>=640 and duration>=want_dur. Used by plan.py for batch vision check.
import json, os, sys, urllib.parse, urllib.request

from dotenv import load_dotenv

query = sys.argv[1]
want_dur = float(sys.argv[2])
env_path = sys.argv[3] if len(sys.argv) > 3 else None

load_dotenv(env_path) if env_path else load_dotenv()
key = os.environ.get("PEXELS_API_KEY", "").strip()

if not key:
    print("broll-pick: PEXELS_API_KEY missing", file=sys.stderr)
    json.dump({"candidates": []}, sys.stdout)
    sys.exit(0)

url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode({
    "query": query, "per_page": 10, "orientation": "landscape", "size": "medium",
})
req = urllib.request.Request(url, headers={
    "Authorization": key,
    "User-Agent": "shorts-broll/1.0",
})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
except Exception as e:
    print(f"broll-pick: pexels search failed for {query!r}: {e}", file=sys.stderr)
    json.dump({"candidates": []}, sys.stdout)
    sys.exit(0)

candidates = []
for v in data.get("videos", []):
    if v.get("duration", 0) < want_dur:
        continue
    files = sorted(
        [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"],
        key=lambda f: f.get("width", 9999),
    )
    chosen = None
    for f in files:
        if f.get("width", 0) >= 640:
            chosen = f.get("link")
            break
    if chosen:
        candidates.append({
            "link": chosen,
            "duration": v.get("duration"),
            "video_id": v.get("id"),
        })
    if len(candidates) >= 3:
        break

json.dump({"candidates": candidates}, sys.stdout)
