#!/usr/bin/env python3
import sys

topic = sys.argv[1]
query = sys.argv[2]
grid = sys.argv[3]
ts = sys.argv[4]  # comma-separated source timestamps for frames 0,1,2
context = sys.argv[5] if len(sys.argv) > 5 else ""  # what the speaker says here

ctx_line = f'\nAt this moment the speaker is saying: "{context.strip()}"\n' if context.strip() else ""

print(f"""You are the editor vetting candidate B-ROLL footage for a short video. The
cutaway will fully replace the screen while the speaker keeps talking, so it must
ILLUSTRATE this moment — both the subject AND the tone/context must fit.

Intended cutaway: {topic!r} (search query was {query!r}).
{ctx_line}
The image strip below holds 3 frames sampled from one candidate video, left to
right = FRAME 0, FRAME 1, FRAME 2, taken at source timestamps {ts}s respectively.

Read the image with your Read tool: {grid}

Decide STRICTLY:
- Does a frame actually show {topic!r} in a way that fits the moment above?
- REJECT literal-but-wrong matches: footage that technically contains the keyword
  but has the wrong context or tone (e.g. a cat chasing a laser pointer when the
  story needs a menacing sniper laser dot; a comedy clip under a serious beat).
- REJECT talking heads, logos, title/end cards, memes, reaction-face thumbnails,
  watermarked stock-preview grids, and unrelated scenes.
- If a frame is clearly on-subject AND on-tone, pick the single strongest one.

Return ONLY one JSON object on a single line, no prose:
  {{"match":true,"best":0}}
  {{"match":false}}
""")
