#!/usr/bin/env python3
import json, re, sys

reply = open(sys.argv[1]).read() if sys.argv[1] != "-" else ""
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0

MIN_DUR = 2.0
MAX_DUR = 5.0

picks = []
m = re.search(r"\{.*\}", reply, re.S)
if m:
    try:
        raw = json.loads(m.group(0)).get("picks", [])
    except Exception:
        raw = []
    raw.sort(key=lambda p: float(p.get("t0", 0)))
    last_end = 0.0
    for p in raw:
        try:
            t0 = float(p["t0"]); d = float(p["dur"]); q = str(p["query"]).strip()
        except Exception:
            continue
        anchor = str(p.get("anchor", "")).strip()
        if not q or d <= 0:
            continue
        if dur and (t0 < 2.0 or t0 >= dur - 0.3):
            continue
        if t0 < last_end:
            t0 = last_end
        max_end = dur - 0.3 if dur else t0 + d
        end = min(t0 + d, t0 + MAX_DUR, max_end)
        if end - t0 < MIN_DUR:
            continue
        picks.append({
            "t0": round(t0, 3),
            "dur": round(end - t0, 3),
            "query": q,
            "anchor": anchor,
        })
        last_end = end

json.dump({"picks": picks}, sys.stdout, indent=2)
