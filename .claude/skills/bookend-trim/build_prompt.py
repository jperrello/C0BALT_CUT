#!/usr/bin/env python3
# build a single prompt asking claude to pick the best sentence-completing
# bookends for each span. context = whisper transcript-segment lines within
# ±extend of the original [t0, t1]. claude picks t0/t1 from line boundaries
# present in the window.
import json, sys

segments_path, transcript_path, extend = sys.argv[1:4]
extend = float(extend)

segs = json.load(open(segments_path)).get("shorts", [])
lines = json.load(open(transcript_path)).get("segments", [])


def window(t0, t1):
    out = []
    for ln in lines:
        if ln["t1"] >= t0 - extend and ln["t0"] <= t1 + extend:
            out.append(f"[{ln['t0']:.2f}-{ln['t1']:.2f}] {ln['text'].strip()}")
    return "\n".join(out)


blocks = []
for i, s in enumerate(segs):
    blocks.append(
        f"=== SPAN {i}  current [{s['t0']:.2f}-{s['t1']:.2f}] ===\n{window(s['t0'], s['t1'])}"
    )

joined = "\n\n".join(blocks)

print(f"""You are adjusting the START and END timestamps of picked video clips so
each clip BEGINS at the start of a complete sentence/thought and ENDS at the
end of a complete sentence/thought. The video transcript has NO punctuation —
infer sentence boundaries from the wording itself.

For each SPAN below, the current [t0, t1] is shown plus surrounding transcript
lines within ±{extend:.0f}s. Each line is `[start-end] text`.

Your job:
  - new_t0 = a START timestamp that begins a complete thought. Prefer the
    line-start boundary closest to current t0 that does NOT cut into the
    middle of a sentence. You may pull back (earlier) OR push forward
    (later) — whichever yields a cleaner sentence start. Stay within the
    window.
  - new_t1 = an END timestamp that completes a thought (end of a sentence,
    not mid-clause). Prefer the line-end boundary closest to current t1
    that completes a sentence. You may extend (later) OR pull back (earlier).
    Prefer extending — landing on a complete thought is more important than
    keeping the clip short.

Rules:
  - new_t0 and new_t1 must be timestamps that appear as line boundaries in
    the SPAN's window above (start of a line for new_t0, end of a line for
    new_t1).
  - new_t1 > new_t0, and (new_t1 - new_t0) must be at least 5 seconds.
  - If no clean boundary exists, return the current t0/t1 unchanged and
    note "no clean boundary".

Spans:

{joined}

Reply with ONLY a JSON object (no prose, no code fences):
{{"adjustments": [
  {{"span": <int>, "t0": <float>, "t1": <float>, "note": "<short reason>"}}
]}}""")
