#!/usr/bin/env python3
# Assemble broll_plan.json from accumulated picks + ingested ids.
# argv: picks.jsonl ids.txt vision_used vision_cap chunks_mtime out.json
import json, sys, os

picks_path, ids_path, used, cap, cm, out = sys.argv[1:7]

picks = []
if os.path.exists(picks_path):
    for line in open(picks_path):
        line = line.strip()
        if line:
            picks.append(json.loads(line))
picks.sort(key=lambda p: p["t0"])

ids = []
if os.path.exists(ids_path):
    for line in open(ids_path):
        v = line.strip()
        if v and v not in ids:
            ids.append(v)

json.dump({
    "picks": picks,
    "ingested_video_ids": ids,
    "vision_calls_used": int(used),
    "vision_cap": int(cap),
    "chunks_mtime": float(cm),
}, open(out, "w"), indent=2)
print(out)
