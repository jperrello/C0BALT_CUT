#!/usr/bin/env python3
# Parse Claude's reply, validate spans, write segments.json to stdout.
import json, re, sys

reply_path, n, dmin, dmax, transcript_path = sys.argv[1:6]
topics_path = sys.argv[6] if len(sys.argv) > 6 else ""
n, dmin, dmax = int(n), float(dmin), float(dmax)

topics = []
if topics_path:
    try:
        topics = json.load(open(topics_path)).get("topics", [])
    except FileNotFoundError:
        topics = []

def topic_of(t0, t1):
    for t in topics:
        if t0 >= t["t0"] - 0.25 and t1 <= t["t1"] + 0.25:
            return t
    return None

text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
if not m:
    print(f"pick-segments: no JSON in reply: {text!r}", file=sys.stderr)
    sys.exit(1)
data = json.loads(m.group(0))

tx = json.load(open(transcript_path))
duration = (tx.get("segments") or [{"t1": 0}])[-1]["t1"]

shorts = []
seen = []
for sh in data.get("shorts", []):
    t0 = float(sh["t0"])
    t1 = float(sh["t1"])
    if t1 <= t0:
        continue
    if duration and (t0 < 0 or t1 > duration + 1):
        continue
    dur = t1 - t0
    if dur < dmin - 0.5 or dur > dmax + 0.5:
        continue
    if any(not (t1 <= a or t0 >= b) for a, b in seen):
        continue
    tp = topic_of(t0, t1) if topics else None
    if topics and tp is None:
        print(f"pick-segments: dropping span {t0:.1f}-{t1:.1f} (crosses topic boundary)", file=sys.stderr)
        continue
    seen.append((t0, t1))
    item = {
        "t0": round(t0, 2),
        "t1": round(t1, 2),
        "rationale": sh.get("rationale", "")[:280],
        "title_suggestion": sh.get("title_suggestion", "")[:120],
    }
    if tp is not None:
        item["topic"] = tp.get("title", "")
    shorts.append(item)
    if len(shorts) >= n:
        break

shorts.sort(key=lambda s: s["t0"])
json.dump({"source": tx.get("source", ""), "shorts": shorts}, sys.stdout, indent=2)
