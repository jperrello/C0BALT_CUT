#!/usr/bin/env python3
# build the comedy-beat marking prompt from a clip-local word-timed transcript.
import json, sys

tx = json.load(open(sys.argv[1]))
words = tx.get("words", [])

lines = []
cur, t0 = [], None
for w in words:
    if t0 is None:
        t0 = w["t0"]
    cur.append(w["w"])
    if len(cur) >= 10:
        lines.append(f"[{t0:.2f}] {' '.join(cur)}")
        cur, t0 = [], None
if cur:
    lines.append(f"[{t0:.2f}] {' '.join(cur)}")

dur = words[-1]["t1"] if words else 0.0

print(f"""You are a shorts editor placing meme sound effects on a {dur:.1f}s clip.

Transcript (each line prefixed with its start time in seconds; words are evenly spread within a line):
{chr(10).join(lines)}

Mark 0-4 beats where a meme SFX would AMPLIFY the moment. Types:
  - "boom"    (vine boom): a punchline, absurd claim, or savage line LANDING. The biggest laugh/shock beat.
  - "scratch" (record scratch): a wait-WHAT pivot — the moment something ironic or contradictory drops.
  - "ding"    (bell): a sharp insight, tip, or "that's actually smart" realization clicking into place.

Rules:
  - Only genuinely strong beats. A mediocre beat with a boom on it reads as cringe — when in doubt, mark NOTHING. Zero beats is a perfectly good answer.
  - t = the second the landing WORD ends (interpolate within a line). The SFX hits right as the word lands.
  - Beats at least 3s apart. Never in the first 1s. Keep the ENDING clean: place NO beat in the final ~4s — the short lands on a "FOLLOW FOR MORE" card and a bell/boom ringing over it reads as a glitch.

Reply with ONLY a JSON object (no prose, no code fences):
{{"beats": [{{"t": <float>, "type": "boom|scratch|ding", "why": "<5 words>"}}]}}""")
