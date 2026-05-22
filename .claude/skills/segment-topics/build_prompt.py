#!/usr/bin/env python3
# Build a prompt asking Claude to partition a transcript into topical chapters.
import json, sys

tx = json.load(open(sys.argv[1]))
segments = tx.get("segments") or []
if not segments and tx.get("words"):
    cur, t0 = [], None
    for w in tx["words"]:
        if t0 is None:
            t0 = w["t0"]
        cur.append(w["w"])
        if w["t1"] - t0 >= 10:
            segments.append({"t0": t0, "t1": w["t1"], "text": " ".join(cur)})
            cur, t0 = [], None
    if cur:
        segments.append({"t0": t0 or 0, "t1": tx["words"][-1]["t1"], "text": " ".join(cur)})

duration = segments[-1]["t1"] if segments else 0

lines = [f"[{s['t0']:.1f}-{s['t1']:.1f}] {s['text'].strip()}" for s in segments]
block = "\n".join(lines)

# Target topic count: roughly one per ~90s, clamped to [3, 20]
target = max(3, min(20, int(duration / 90) or 3))

print(f"""You are splitting a video transcript into contiguous TOPICAL CHAPTERS.

A "topic" is one self-contained subject: one bit, one anecdote, one challenge, one rant, one segment of an interview. When the speaker changes subject — new game, new story, new question, scene cut to unrelated footage — that is a topic boundary.

Source duration: {duration:.1f}s
Target: about {target} topics. Favor fewer, longer topics over many short ones. Do not split inside a single coherent thought.

Transcript (timestamped lines, seconds):
{block}

Requirements:
- Topics are CONTIGUOUS and NON-OVERLAPPING: topics[i].t1 == topics[i+1].t0.
- Together they cover [0, {duration:.1f}].
- t0 and t1 should land on the boundaries of the transcript lines above (don't cut mid-line).
- Each topic gets a short title (≤8 words) and a one-sentence summary.

Reply with ONLY a JSON object (no prose, no code fences):
{{"topics": [{{"t0": <float>, "t1": <float>, "title": "<short>", "summary": "<one sentence>"}}]}}""")
