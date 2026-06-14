#!/usr/bin/env python3
# Build ONE prompt asking claude, per span, whether the assembled story ARC
# lands as a complete standalone short. For each span we render the assembled
# arc text (the words inside the span's cuts, in order) plus a TAIL LOOKAHEAD —
# the source lines AFTER the last cut's end, up to the remaining dmax headroom.
# Claude returns complete | truncated | needs_more_tail, and when the payoff
# lands just past the current end it gives extend_t1 (a source line-end inside
# the lookahead) so parse_reply can nudge t1 outward — within dmax.
import json, sys

segments_path, transcript_path, dmax = sys.argv[1:4]
dmax = float(dmax)

segs = json.load(open(segments_path)).get("shorts", [])
lines = json.load(open(transcript_path)).get("segments", [])


def arc(cuts):
    out = []
    for a, b in cuts:
        for ln in lines:
            if ln["t1"] > a and ln["t0"] < b:
                out.append(ln["text"].strip())
    return " ".join(out)


def lookahead(end, headroom):
    out = []
    for ln in lines:
        if ln["t0"] >= end - 0.25 and ln["t0"] <= end + headroom:
            out.append(f"[{ln['t0']:.2f}-{ln['t1']:.2f}] {ln['text'].strip()}")
    return "\n".join(out) or "(no further source — clip is at the end of the video)"


blocks = []
for i, s in enumerate(segs):
    cuts = s.get("cuts") or [[s["t0"], s["t1"]]]
    selected = sum(b - a for a, b in cuts)
    end = cuts[-1][1]
    headroom = max(0.0, dmax - selected)
    blocks.append(
        f"""=== SPAN {i}  selected {selected:.1f}s  (dmax {dmax:.0f}s, tail headroom {headroom:.1f}s) ===
ASSEMBLED ARC (what the short currently says):
{arc(cuts)}

TAIL LOOKAHEAD (source lines AFTER the current end {end:.2f}s — candidate landing material):
{lookahead(end, headroom)}"""
    )

joined = "\n\n".join(blocks)

print(f"""You are a shorts editor doing a COMPLETENESS pass. For each SPAN you see the
ASSEMBLED ARC (the text the short currently contains) and a TAIL LOOKAHEAD (the
source lines that come right after the current ending). The transcript has NO
punctuation — infer sentence/thought boundaries from the wording.

Judge whether the arc LANDS as a standalone short: setup -> turn -> and a real
LANDING (the speaker says why the turn matters / completes the thought), not an
abrupt stop on a phrase that leaves the viewer asking "so what?" or "...and?".

For each span return one verdict:
  - "complete": the arc already lands. No change.
  - "needs_more_tail": the payoff/landing is cut off, AND the missing landing
    is present in the TAIL LOOKAHEAD. Give extend_t1 = the END timestamp of the
    line in the lookahead that completes the thought. It MUST be a line-end that
    appears in that span's lookahead, and the resulting clip must stay within
    the dmax tail headroom shown.
  - "truncated": the arc ends abruptly but the landing is NOT recoverable from
    the lookahead (it's not there, or extending would blow past dmax). No
    change — just flag it.

Bias toward "complete". Only extend when a SHORT tail (ideally one sentence)
clearly turns an abrupt stop into a satisfying landing. Never extend just to be
longer.

Spans:

{joined}

Reply with ONLY a JSON object (no prose, no code fences):
{{"verdicts": [
  {{"span": <int>, "verdict": "complete|needs_more_tail|truncated", "extend_t1": <float or null>, "note": "<short reason>"}}
]}}""")
