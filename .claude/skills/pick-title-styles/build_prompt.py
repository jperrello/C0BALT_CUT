#!/usr/bin/env python3
import json, os, sys

segments_path, transcript_path = sys.argv[1:3]
recent_path = sys.argv[3] if len(sys.argv) > 3 else ""

doc = json.load(open(segments_path))
segs = doc.get("shorts", [])
tx = json.load(open(transcript_path))
lines = tx.get("segments") or []


def excerpt(t0, t1, cap=14):
    out = []
    for ln in lines:
        mid = (ln["t0"] + ln["t1"]) / 2
        if t0 - 0.5 <= mid <= t1 + 0.5:
            out.append(ln["text"].strip())
    if len(out) > cap:
        keep = cap // 2
        out = out[:keep] + ["[...]"] + out[-keep:]
    return " ".join(out)


blocks = []
for i, s in enumerate(segs):
    blocks.append(f"""=== SPAN {i} ===
topic: {s.get('topic', '?')}
rationale: {s.get('rationale', '?')}
transcript: {excerpt(s['t0'], s['t1'])}""")

recent = []
if recent_path and os.path.exists(recent_path):
    recent = [l.strip() for l in open(recent_path) if l.strip()][-10:]
recency = ""
if recent:
    counts = {}
    for r in recent:
        counts[r] = counts.get(r, 0) + 1
    summary = ", ".join(f"{k} x{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    recency = f"""
Recently used across past runs (most-used first): {summary}.
When two styles fit a span comparably, prefer the LESS recently used one."""

cap = max(1, (len(segs) + 1) // 2)

print(f"""You are assigning an intro TITLE-CARD STYLE to each picked video span.

The styles (pick by the span's CONTENT and EMOTIONAL REGISTER, not at random):
  - "slam"       — hype, stunts, big reveals, shock, money, high energy. Title slams in with a boom.
  - "typewriter" — mystery, true-crime beats, secrets, investigations, story setups. Chars type in with clicks.
  - "glitch"     — tech, AI, internet culture, disruption, anything 'the future just broke'. RGB-split flicker.
  - "bounce"     — comedy, absurd anecdotes, self-deprecation, playful roasts. Words pop in cartoonishly.
  - "cinematic"  — reflective, profound, philosophical, emotional weight, life advice. Serif tracks in slowly.

Rules:
  1. FIT WINS. A strongly-typed span (a crime story, an AI rant, a joke) gets its
     obvious style even if recently used.
  2. When fit is comparable, SPREAD picks across the run for variety.
  3. Never assign one style to more than {cap} of the {len(segs)} span(s).
  4. Most podcast spans are tonally neutral 'interesting conversation' — that is
     exactly where rules 2-3 decide, not rule 1.{recency}

Spans:

{chr(10).join(blocks)}

Reply with ONLY a JSON object (no prose, no code fences):
{{"styles": [
  {{"span": <int>, "style": "slam" | "typewriter" | "glitch" | "bounce" | "cinematic", "note": "<short reason>"}}
]}}""")
