#!/usr/bin/env python3
# Assemble broll_plan.json from accumulated picks + ingested ids.
# argv: picks.jsonl ids.txt vision_used vision_cap chunks_mtime out.json [transcript.json]
import json, sys, os

picks_path, ids_path, used, cap, cm, out = sys.argv[1:7]
tx_path = sys.argv[7] if len(sys.argv) > 7 else ""

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

# cutaway coverage vs the clip runtime — the engagement lever (cutaway_fraction
# correlates +0.68 with likes/1k; viral floor ~0.6). Warn-only, never blocks.
cover = None
if tx_path and os.path.exists(tx_path):
    try:
        tx = json.load(open(tx_path))
        pts = tx.get("words") or tx.get("segments") or []
        dur = max((float(p["t1"]) for p in pts), default=0.0)
        if dur > 0:
            cover = round(min(1.0, sum(float(p["t1"]) - float(p["t0"]) for p in picks) / dur), 3)
    except Exception:
        cover = None

floor = float(os.environ.get("BROLL_MIN_COVER", "0.6"))
if cover is not None and cover < floor:
    print(f"broll-pick: WARN cutaway coverage {cover:.2f} below floor {floor:.2f} "
          f"(engagement lever — see perf-style analysis)", file=sys.stderr)

json.dump({
    "picks": picks,
    "ingested_video_ids": ids,
    "vision_calls_used": int(used),
    "vision_cap": int(cap),
    "chunks_mtime": float(cm),
    "cutaway_coverage": cover,
}, open(out, "w"), indent=2)
print(out)
