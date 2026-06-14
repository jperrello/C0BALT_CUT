#!/usr/bin/env python3
# Extract the candidate clip-moments from an rlm segment-topics reply and write
# candidates.hint.json (consumed by pick-segments as a discovery HINT). Best
# effort: a reply with no candidates yields an empty hint, never an error.
import json, re, sys

reply_path, transcript_path = sys.argv[1:3]
tx = json.load(open(transcript_path))
segs = tx.get("segments") or []
duration = segs[-1]["t1"] if segs else 0

text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
cands = []
if m:
    try:
        for c in json.loads(m.group(0)).get("candidates", []):
            t0 = float(c["t0"]); t1 = float(c["t1"])
            if t1 <= t0 or t0 < 0 or (duration and t1 > duration + 5):
                continue
            cands.append({
                "t0": round(t0, 2),
                "t1": round(t1, 2),
                "quote": str(c.get("quote", "")).strip()[:400],
                "why": str(c.get("why", "")).strip()[:200],
            })
    except (ValueError, KeyError, TypeError):
        cands = []

cands.sort(key=lambda c: c["t0"])
json.dump({"source": tx.get("source", ""), "candidates": cands}, sys.stdout, indent=2)
