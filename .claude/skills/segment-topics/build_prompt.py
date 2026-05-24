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

# Target topic count: roughly one per ~45s, clamped to [4, 40].
# Tighter than before so downstream pick-segments has less room to straddle.
target = max(4, min(40, int(duration / 45) or 4))

print(f"""You are splitting a video transcript into contiguous TOPICAL CHAPTERS.

A "topic" is ONE self-contained subject: one bit, one anecdote, one challenge, one rant, one question-and-answer, one game moment, one reaction story. The instant the speaker pivots — new game, new story, new question, scene change, new opponent, "anyway / so / next / now / okay so" pivots that introduce a different subject — you START A NEW TOPIC.

Err HEAVILY on the side of MORE, SHORTER topics. A topic that lumps two unrelated bits together causes downstream shorts that jump between subjects, which is a hard failure. A topic that is "too narrow" is harmless.

Source duration: {duration:.1f}s
Target: about {target} topics. If in doubt between one big topic and two smaller ones, choose two smaller ones.

Transcript (timestamped lines, seconds):
{block}

Requirements:
- Topics are CONTIGUOUS and NON-OVERLAPPING: topics[i].t1 == topics[i+1].t0.
- Together they cover [0, {duration:.1f}].
- t0 and t1 should land on the boundaries of the transcript lines above (don't cut mid-line).
- Each topic gets a short title (≤8 words) and a one-sentence summary.
- A topic should generally be 20-90s. Avoid topics longer than ~120s — split instead.

Reply with ONLY a JSON object (no prose, no code fences):
{{"topics": [{{"t0": <float>, "t1": <float>, "title": "<short>", "summary": "<one sentence>"}}]}}""")
