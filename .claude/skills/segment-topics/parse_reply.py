#!/usr/bin/env python3
# Parse Claude's reply, validate + repair, write topics.json to stdout.
import json, re, sys

reply_path, transcript_path = sys.argv[1:3]
text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
if not m:
    print(f"segment-topics: no JSON in reply: {text!r}", file=sys.stderr)
    sys.exit(1)
data = json.loads(m.group(0))

tx = json.load(open(transcript_path))
segs = tx.get("segments") or []
duration = segs[-1]["t1"] if segs else 0
boundaries = sorted({0.0, duration, *(s["t0"] for s in segs), *(s["t1"] for s in segs)})

def snap(t):
    if not boundaries:
        return round(float(t), 2)
    return round(min(boundaries, key=lambda b: abs(b - t)), 2)

raw = sorted(data.get("topics", []), key=lambda t: float(t["t0"]))
topics = []
prev_end = 0.0
for t in raw:
    t0 = snap(t["t0"])
    t1 = snap(t["t1"])
    if t1 <= t0:
        continue
    # Force contiguity with previous topic
    t0 = prev_end if topics else 0.0
    if t1 <= t0:
        continue
    topics.append({
        "t0": t0,
        "t1": t1,
        "title": str(t.get("title", "")).strip()[:120],
        "summary": str(t.get("summary", "")).strip()[:400],
    })
    prev_end = t1

# Extend last topic to cover full duration
if topics and duration and topics[-1]["t1"] < duration:
    topics[-1]["t1"] = round(duration, 2)
# If Claude returned nothing usable, fall back to one big topic.
if not topics and duration:
    topics = [{"t0": 0.0, "t1": round(duration, 2), "title": "Full video", "summary": ""}]

json.dump({"source": tx.get("source", ""), "topics": topics}, sys.stdout, indent=2)
