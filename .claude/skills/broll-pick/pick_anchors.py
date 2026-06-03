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

print(f"""You are the EDITOR choosing B-ROLL cutaways for a short-form vertical video. The
speaker talks over the whole clip; during a cutaway the picture is fully replaced
by footage that ILLUSTRATES what's being said, then cuts back to the talking head.
Think like a viral creator: cut away OFTEN, and make every cutaway feel like it
belongs to THIS story.

Source video title: {title!r}

Full clip transcript:
{text}

The clip is split into numbered CAPTION CHUNKS (each is one short phrase). Cutaway
windows MUST be expressed as a range of whole chunk indices so no cut lands
mid-word:

{block}

HOW TO THINK ABOUT EACH BEAT — do NOT just grab literal keyword objects. For each
moment ask "what would an editor put on screen here?" Footage can be:
  - LITERAL objects/animals/places ("hippopotamus", "Ford Bronco").
  - SCENE-SETTING / establishing shots that set the mood of the moment
    ("dark suburban house at night", "empty ransacked living room").
  - ACTION / gesture ("hand turning key in a door lock", "person running scared").
  - EVOCATIVE / conceptual shots that visualize the FEELING or implied image
    ("red sniper laser dot on a wall", "security camera footage at night").

CRITICAL — match the STORY, not the dictionary. Example: in a tense story about
coming home at 3am and seeing a red dot on the door and fearing a stalker, the
beat "a red dot popped up" should cut to a RED SNIPER/LASER SIGHT DOT ON A WALL or
a rifle scope crosshair — NOT a cat chasing a laser pointer (literally a red dot,
totally wrong tone). Pick footage whose CONTEXT and MOOD fit the moment.

DENSITY — be aggressive. Cover the clip with cutaways the way a top creator would:
aim for a cutaway on roughly every other beat where a sensible visual exists. Use
6-10 windows total (across all anchors) when the clip supports it; a window is
usually 1-2 chunks. For any anchor with a clear subject, define MULTIPLE windows
intercut with the speaker, each window using a DIFFERENT query so the footage
varies (e.g. hippo: "hippo underwater", "hippo running on land", "hippo in grass").

Rules:
- chunk indices are 0..{len(chunks)-1}. c0 <= c1. Windows must not overlap.
- query: 2-6 words, concrete and literally searchable on YouTube, describing the
  ACTUAL footage you want (include mood words like "at night", "scared", "empty"
  when they matter). No proper nouns unless visually iconic.
- Skip only beats with genuinely no sensible visual (pure abstract filler).

Return ONLY one JSON object on a single line, no prose, no code fences:

{{"anchors":[{{"topic":"hippopotamus","anchor_word":"hippo","windows":[{{"c0":2,"c1":2,"query":"hippo swimming underwater"}},{{"c0":5,"c1":6,"query":"hippo running on land"}}]}}]}}
""")
