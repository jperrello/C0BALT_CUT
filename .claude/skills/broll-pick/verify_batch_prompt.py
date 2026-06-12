#!/usr/bin/env python3
# Build ONE vision-verify prompt covering several candidates (one per window).
# argv: manifest.json — [{"n":int,"topic","query","context","grid","ts"}]
import json, sys

man = json.load(open(sys.argv[1]))

print("""You are the editor vetting candidate B-ROLL footage for a short video. Each
cutaway will fully replace the screen while the speaker keeps talking, so it must
ILLUSTRATE its moment — both the subject AND the tone/context must fit.

Below are several INDEPENDENT candidates. For each one, read its image strip with
your Read tool. Each strip holds 3 frames from one candidate video, left to right
= FRAME 0, FRAME 1, FRAME 2, taken at the listed source timestamps.
""")

for c in man:
    ctx = (c.get("context") or "").strip()
    ctx_line = f'\n  At this moment the speaker is saying: "{ctx}"' if ctx else ""
    print(f"""CANDIDATE {c['n']}:
  Intended cutaway: {c['topic']!r} (search query was {c['query']!r}).{ctx_line}
  Image strip (frames at {c['ts']}s): read {c['grid']}
""")

print("""For EACH candidate decide STRICTLY and independently:
- Does a frame actually show the intended cutaway in a way that fits its moment?
- REJECT literal-but-wrong matches: footage that technically contains the keyword
  but has the wrong context or tone (e.g. a cat chasing a laser pointer when the
  story needs a menacing sniper laser dot; a comedy clip under a serious beat).
- REJECT talking heads, logos, title/end cards, memes, reaction-face thumbnails,
  watermarked stock-preview grids, and unrelated scenes.
- If a frame is clearly on-subject AND on-tone, pick the single strongest one.

Return ONLY one JSON object on a single line, no prose — one entry per candidate:
  {"results":[{"n":<candidate number>,"match":true,"best":0|1|2},{"n":<candidate number>,"match":false}, ...]}
""")
