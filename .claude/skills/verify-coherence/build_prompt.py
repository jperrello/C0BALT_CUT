#!/usr/bin/env python3
import json, sys

segments_path, transcript_path = sys.argv[1:3]

segs = json.load(open(segments_path)).get("shorts", [])
tx = json.load(open(transcript_path))
lines = tx.get("segments") or []

def slice_for(t0, t1):
    out = []
    for ln in lines:
        mid = (ln["t0"] + ln["t1"]) / 2
        if t0 - 0.5 <= mid <= t1 + 0.5:
            out.append(f"[{ln['t0']:.1f}-{ln['t1']:.1f}] {ln['text'].strip()}")
    return "\n".join(out)

blocks = []
for i, s in enumerate(segs):
    blocks.append(f"=== SPAN {i} [{s['t0']:.2f}-{s['t1']:.2f}] ===\n{slice_for(s['t0'], s['t1'])}")

joined = "\n\n".join(blocks)

print(f"""You are auditing picked video spans for TOPICAL COHERENCE.

For each span below, decide:
  - "keep"     — span is about ONE coherent topic from start to end.
  - "tighten"  — span pivots partway through (e.g. anecdote A then anecdote B,
                  game 1 then game 2, question 1 then question 2). Return the
                  trimmed [t0, t1] containing ONLY the dominant topic (the
                  longer one, or if equal length, the one with the stronger
                  opening hook).

Bias toward "keep". Only tighten when the pivot to a second unrelated topic is
unambiguous in the transcript. Off-topic asides under ~3s do not count.

When tightening:
  - Pick t0/t1 that fall on the transcript line boundaries shown.
  - Keep the trimmed span as long as possible while excluding the second topic.

Spans to audit:

{joined}

Reply with ONLY a JSON object (no prose, no code fences):
{{"verdicts": [
  {{"span": <int>, "action": "keep" | "tighten", "t0": <float>, "t1": <float>, "note": "<short reason>"}}
]}}""")
