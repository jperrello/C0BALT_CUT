#!/usr/bin/env python3
import json, sys

tx = json.load(open(sys.argv[1]))
chunks = json.load(open(sys.argv[2])).get("chunks", [])
ingest = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else {}

title = ingest.get("title", "")
words = [w for w in tx.get("words", []) if str(w.get("w", "")).strip()]
text = " ".join(str(w["w"]).strip() for w in words)

lines = []
for i, c in enumerate(chunks):
    lines.append(f"{i}\t[{c['t0']:.2f}-{c['t1']:.2f}]\t{c.get('text','').strip()}")
block = "\n".join(lines)

print(f"""You are choosing B-ROLL cutaways for a short-form vertical video. The speaker
talks over the whole clip; you pick the few strongest CONCRETE, VISUALIZABLE
nouns/topics and overlay stock footage of them, intercut beat-by-beat with the
talking head.

Source video title: {title!r}

Full clip transcript:
{text}

The clip is split into numbered CAPTION CHUNKS (each is one short phrase). Cutaway
windows MUST be expressed as a range of whole chunk indices so no cut lands
mid-word:

{block}

Pick the 3-5 STRONGEST visualizable anchors (NOUN / VERB / EMOTION / PIVOT model).
Skip abstract talk with no clear visual. For each anchor, define MULTIPLE short
cutaway windows (1-3) intercut with the speaker — each window covers a small range
of whole chunks, and each window of the SAME anchor should use a DIFFERENT search
query so the footage varies (e.g. a hippo: "hippo underwater", "hippo running on
land", "hippo in grass"). Windows should be short (often a single chunk) and land
on the chunk where the anchor word is actually spoken.

Rules:
- chunk indices are 0..{len(chunks)-1}. c0 <= c1. Windows must not overlap.
- query: 2-6 words, concrete and literally searchable on YouTube. No proper nouns
  unless they are visually iconic.
- Prefer fewer, stronger anchors over covering every noun.

Return ONLY one JSON object on a single line, no prose, no code fences:

{{"anchors":[{{"topic":"hippopotamus","anchor_word":"hippo","windows":[{{"c0":2,"c1":2,"query":"hippo swimming underwater"}},{{"c0":5,"c1":6,"query":"hippo running on land"}}]}}]}}
""")
