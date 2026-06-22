#!/usr/bin/env python3
# Parse Claude's reply, validate + repair, write topics.json to stdout.
import json, re, sys

reply_path, transcript_path = sys.argv[1:3]
text = open(reply_path).read()

def extract_json(s):
    # The reduce reply may wrap its JSON in prose that itself contains braces, so a
    # greedy {.*} can over-capture into invalid JSON. Try greedy first, then walk
    # balanced top-level {...} candidates and return the first that parses.
    m = re.search(r"\{.*\}", s, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            pass
    depth = start = 0
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except ValueError:
                    continue
    return None

data = extract_json(text)
if not isinstance(data, dict):
    print(f"segment-topics: no parseable JSON in reply: {text[:200]!r}", file=sys.stderr)
    sys.exit(1)

tx = json.load(open(transcript_path))
segs = tx.get("segments") or []
duration = segs[-1]["t1"] if segs else 0
boundaries = sorted({0.0, duration, *(s["t0"] for s in segs), *(s["t1"] for s in segs)})

def snap(t):
    if not boundaries:
        return round(float(t), 2)
    return round(min(boundaries, key=lambda b: abs(b - t)), 2)

# Coerce/skip malformed topic entries (a missing/non-numeric t0/t1, a non-dict, or
# topics not even a list) instead of crashing — a single bad entry must not abort
# the run; the contiguity loop + one-big-topic fallback below repair the rest.
raw = []
for t in (data.get("topics") if isinstance(data.get("topics"), list) else []):
    if not isinstance(t, dict):
        continue
    try:
        a, b = float(t["t0"]), float(t["t1"])
    except (KeyError, TypeError, ValueError):
        continue
    raw.append({"t0": a, "t1": b, "title": t.get("title", ""), "summary": t.get("summary", "")})
raw.sort(key=lambda t: t["t0"])

# Coverage diagnostic (shorts-upk safety net): the orchestrator is asked to
# verify each chunk's topics tile its window and re-dispatch gappy chunks, but
# if a hole still slips through, warn here. The contiguity-forcing below repairs
# the output either way; this only surfaces a likely lost MAP chunk for tuning.
if raw and duration:
    cover = max(0.0, min(duration, float(raw[0]["t0"])))  # leading gap
    biggest = float(raw[0]["t0"])
    prev = float(raw[0]["t1"])
    for t in raw[1:]:
        gap = float(t["t0"]) - prev
        if gap > biggest:
            biggest = gap
        prev = max(prev, float(t["t1"]))
    biggest = max(biggest, duration - prev)               # trailing gap
    if biggest > max(120.0, duration * 0.05):
        print(f"segment-topics: WARN coverage gap ~{biggest:.0f}s in topics "
              f"(duration {duration:.0f}s) — a MAP chunk may have been lost",
              file=sys.stderr)

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
