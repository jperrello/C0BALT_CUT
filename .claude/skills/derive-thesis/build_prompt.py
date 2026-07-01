#!/usr/bin/env python3
# Build the derive-thesis prompt: the chapter list is the source digest.
import json, sys

transcript_path, topics_path = sys.argv[1:3]

topics = json.load(open(topics_path)).get("topics", [])
tx = json.load(open(transcript_path))
segs = tx.get("segments") or []
duration = segs[-1]["t1"] if segs else 0

topic_block = "\n".join(
    f"  [{t.get('t0',0):.0f}-{t.get('t1',0):.0f}] {str(t.get('title','')).strip()}: {str(t.get('summary','')).strip()}"
    for t in topics
) or "(no topics)"

print(f"""You are identifying the CENTRAL SUBJECT of a long-form source video, so a shorts editor can tell ON-SPINE moments from off-spine tangents.

Source duration: {duration:.0f}s. Below is the full chapter list (every topical region, in order):

{topic_block}

A long talk wanders — it has ONE core throughline plus many entertaining tangents (a funny anecdote, an unrelated aside, a guest's side story). Name the throughline; do NOT summarize every chapter.

Return:
  - subject: 2-6 words naming what THIS source is fundamentally about — the guest + core theme (e.g. "Donald Hoffman on consciousness and reality"). Not a single chapter, not a tangent; the spine the episode keeps returning to.
  - thesis_sentence: one sentence stating the core argument/throughline a viewer would take away.
  - key_threads: 3-6 short phrases naming the ON-SPINE sub-themes that advance the subject (the ideas a good short SHOULD be about). Exclude one-off tangents.

Reply with ONLY a JSON object (no prose, no code fences):
{{"subject": "<2-6 words>", "thesis_sentence": "<one sentence>", "key_threads": ["<phrase>", "<phrase>", "..."]}}""")
