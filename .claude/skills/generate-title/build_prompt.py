#!/usr/bin/env python3
import json, sys

transcript_path, ingest_path = sys.argv[1:3]

tx = json.load(open(transcript_path))
try:
    ing = json.load(open(ingest_path))
except Exception:
    ing = {}

segs = tx.get("segments") or []
if segs:
    body = "\n".join(f"[{s['t0']:.1f}-{s['t1']:.1f}] {s['text'].strip()}" for s in segs)
else:
    words = tx.get("words", [])
    body = " ".join(str(w["w"]).strip() for w in words)

src_title = str(ing.get("title", "")).strip()
src_uploader = str(ing.get("uploader") or ing.get("channel") or "").strip()
src_url = str(ing.get("url", "")).strip()

meta_lines = []
if src_title:    meta_lines.append(f"Source video title : {src_title}")
if src_uploader: meta_lines.append(f"Source uploader    : {src_uploader}")
if src_url:      meta_lines.append(f"Source URL         : {src_url}")
meta = "\n".join(meta_lines) or "(no source metadata)"

print(f"""You are writing the TITLE CARD text for a short-form vertical video clip.

The title is the first thing a viewer sees. It must do all of these:

1. Be written in THIRD PERSON. Never "I", "me", "my", "we", "us".
2. NAME THE SUBJECT — the person/character the clip is about. Infer the
   subject's name from the clip transcript and source metadata below. Prefer
   a short familiar name (e.g. "Speed" not "IShowSpeed"; first name only
   when obvious from context).
3. Promise ONE specific moment, reaction, or behavior — not a vague topic.
   Bad: "AN INTERESTING MOMENT". Good: "WHEN SPEED'S CHAIR BROKE MID-STREAM".
4. ≤7 words. ALL CAPS. No emoji. No "?", "!", "...", quotes, or colons.
5. Avoid mushy openers ("CHECK OUT", "YOU WON'T BELIEVE", "THIS IS WHY").
   Use openers like "WATCH", "WHEN", "THE TIME", "ALL THE TIMES", "HOW",
   etc. only when they sharpen the promise — never as filler.

Source metadata:
{meta}

Clip transcript:
{body}

Reply with ONLY the title line, nothing else. No quotes around it. No
explanation. Just the title.""")
