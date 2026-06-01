#!/usr/bin/env python3
import sys

topic = sys.argv[1]
query = sys.argv[2]
grid = sys.argv[3]
ts = sys.argv[4]  # comma-separated source timestamps for frames 0,1,2

print(f"""You are vetting candidate B-ROLL footage for a short video. The cutaway must
clearly show: {topic!r} (search query was {query!r}).

The image strip below holds 3 frames sampled from one candidate video, left to
right = FRAME 0, FRAME 1, FRAME 2, taken at source timestamps {ts}s respectively.

Read the image with your Read tool: {grid}

Decide:
- Is ANY frame clearly, recognisably on-subject for {topic!r}? Reject talking
  heads, logos, title cards, watermarked stock-preview grids, unrelated scenes.
- If yes, which single frame is the strongest, most on-subject shot?

Return ONLY one JSON object on a single line, no prose:
  {{"match":true,"best":0}}
  {{"match":false}}
""")
