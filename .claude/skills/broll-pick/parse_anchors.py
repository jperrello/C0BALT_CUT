#!/usr/bin/env python3
# Parse Claude's anchor reply into a flat, chunk-snapped list of windows.
# Each window: {topic, anchor_word, query, c0, c1, t0, t1}.
# Snapping rules (SPEC): a window covers >=1 whole chunk; if a single chunk is
# too short (< MIN_WIN s) extend forward one chunk; if still degenerate, drop.
import json, re, sys

MIN_WIN = float(sys.argv[3]) if len(sys.argv) > 3 else 0.9

reply = open(sys.argv[1]).read()
chunks = json.load(open(sys.argv[2])).get("chunks", [])
N = len(chunks)


def emit(windows):
    json.dump({"windows": windows}, sys.stdout)


if N == 0:
    emit([])
    sys.exit(0)

m = re.search(r"\{.*\}", reply, re.DOTALL)
obj = None
if m:
    try:
        obj = json.loads(m.group(0))
    except Exception:
        obj = None

if not obj or not isinstance(obj.get("anchors"), list):
    emit([])
    sys.exit(0)

out = []
used = [False] * N  # prevent overlapping windows across all anchors
for a in obj["anchors"]:
    topic = str(a.get("topic", "")).strip()
    anchor_word = str(a.get("anchor_word", topic)).strip()
    for w in a.get("windows", []) or []:
        try:
            c0 = int(w.get("c0"))
            c1 = int(w.get("c1"))
        except Exception:
            continue
        query = str(w.get("query", "")).strip()
        if not query or not topic:
            continue
        if c0 > c1:
            c0, c1 = c1, c0
        c0 = max(0, min(c0, N - 1))
        c1 = max(0, min(c1, N - 1))
        # extend forward while too short
        while (chunks[c1]["t1"] - chunks[c0]["t0"]) < MIN_WIN and c1 < N - 1:
            c1 += 1
        # still degenerate -> drop
        if (chunks[c1]["t1"] - chunks[c0]["t0"]) < MIN_WIN and c0 == c1 and c1 == N - 1:
            continue
        # overlap guard
        if any(used[i] for i in range(c0, c1 + 1)):
            continue
        for i in range(c0, c1 + 1):
            used[i] = True
        out.append({
            "topic": topic,
            "anchor_word": anchor_word,
            "query": query,
            "c0": c0,
            "c1": c1,
            "t0": round(float(chunks[c0]["t0"]), 3),
            "t1": round(float(chunks[c1]["t1"]), 3),
        })

emit(out)
