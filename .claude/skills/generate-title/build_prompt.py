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

The title pops in on the first ~2.5s over the clip's opening frames. It is
the FIRST thing a scrolling stranger sees. They have no context about the
source video, the channel, or the topic. Many of them are watching with
audio muted for the first second. The title must work as a silent visual
hook on its own.

## What the title does

The title LOADS A DEBT that the clip PAYS. It promises one specific
moment, reveal, fact, or contradiction inside the clip — without giving
away the answer. Done right, a viewer who would have swiped past now
holds still to find out what the title was pointing at.

## Step 1 — analyze the clip

Read the transcript below. Decide if the clip has a single clear PAYOFF:
- A reveal (a surprising number, fact, name, outcome)
- A punchline near the end
- A contradiction's resolution
- A reaction or moment the rest of the clip builds toward

Note whether the clip has a clear human/character SUBJECT (a named
person, character, or recognizable figure) — if yes, identify them by
their short familiar name (e.g. "Speed" not "IShowSpeed"; first name only
when obvious from context).

## Step 2 — pick ONE framing

a. Surprising concrete claim
   Lead with the single most surprising verifiable noun/fact the clip
   delivers. Concrete, named, countable. Use this when the clip is
   info-driven or the reveal can be hinted at without spoiling.

b. Specific question / curiosity gap
   Ask a question that references a SPECIFIC named thing from the
   transcript (a person, number, object, place, action). Generic
   curiosity-bait is banned — "WHY DOES YOUR BRAIN DO THIS" fails
   because there is no referent. "WHY JENNY DELETED ONE FRAME" works.

c. Contradiction / "what people get wrong"
   Frame the clip as overturning a common assumption named in or
   implied by the transcript. Use only when the clip actually rebuts
   something — overhype kills retention later.

Stakes/consequence framing is NOT allowed.

## Step 3 — if no clear payoff exists

If the clip is continuous info with no discrete climax, or the
transcript is too sparse to identify a payoff, fall back to framing (a)
only — surface the single most surprising concrete claim. Do not invent
a payoff that is not in the transcript. Always emit a title — never
return empty.

## Hard rules

- THIRD PERSON ONLY. No "I", "me", "my", "we", "us", "our", "you",
  "your". Chyron voice.
- DO NOT REVEAL THE PAYOFF. The title may not contain the punchline
  word, number, or named outcome the clip is built around. If the
  clip's reveal is "octopuses have nine brains", the title may
  reference octopuses, brains, or "more than you'd think" — but never
  "NINE". Load the debt; let the clip pay it.
- COLD-VIEWER TEST. The title must make sense to someone who has never
  heard of the source video, channel, host, or topic. No referent that
  only existing viewers would understand.
- SILENT-COMPREHENSION TEST. The title must convey the promise without
  the audio playing underneath it. Assume the viewer has not heard a
  single word of the clip when they read the title.
- DEFENSIBILITY. A viewer who watches the full clip must agree the
  title was honest. The title must not contradict or overpromise
  relative to what the clip actually delivers. Self-check this before
  emitting.
- NAME THE SUBJECT when there is one. A recognizable named subject is
  itself a hook. Subject-naming composes with any framing.
- READABILITY ceiling: 5th-grade vocabulary. No multisyllabic
  abstractions ("REVELATION", "PHENOMENON", "MECHANISM", "REVENUE",
  "STRATEGY"). Prefer concrete short words ("FIX" not "RESOLUTION",
  "SHOW" not "DEMONSTRATE", "MONEY" not "REVENUE").

## Bans

- No vague pronouns: "THIS ONE TRICK", "THIS ONE THING", "THIS HABIT",
  "THE SECRET". These fail the cold-viewer test silently.
- No clickbait intensifiers: "SHOCKING", "INSANE", "UNBELIEVABLE",
  "CRAZY", "MIND-BLOWING", "WILD". Defensibility lets these slip
  through as technically true; ban them outright.
- No mushy openers used as filler: "CHECK OUT", "YOU WON'T BELIEVE",
  "THIS IS WHY", "HERE'S WHAT HAPPENS". Openers like "WATCH", "WHEN",
  "THE TIME", "HOW", "WHY" are allowed only when they sharpen the
  promise.
- No emoji. No "?", "!", "...", quotes, or colons.

## Format

ALL CAPS. Single line. No more than 7 words. No trailing punctuation.

## Inputs

Source metadata:
{meta}

Clip transcript:
{body}

Reply with ONLY the title line. No quotes. No explanation. Just the
title.""")
