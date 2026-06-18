#!/usr/bin/env python3
import json, sys

transcript_path, ingest_path = sys.argv[1:3]
ctx_path = sys.argv[3] if len(sys.argv) > 3 else ""

tx = json.load(open(transcript_path))
try:
    ing = json.load(open(ingest_path))
except Exception:
    ing = {}

ctx = {}
if ctx_path:
    try:
        ctx = json.load(open(ctx_path))
    except Exception:
        ctx = {}

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

topic = str(ctx.get("topic", "")).strip()
rationale = str(ctx.get("rationale", "")).strip()
suggestion = str(ctx.get("title_suggestion", "")).strip()
ctx_lines = []
if topic:      ctx_lines.append(f"Topic of this moment : {topic}")
if rationale:  ctx_lines.append(f"Why it was picked    : {rationale}")
if suggestion: ctx_lines.append(f"Candidate title      : {suggestion}")
ctx_block = "\n".join(ctx_lines)

step0 = ""
if ctx_block:
    step0 = """## Step 0 — read the register FIRST (do this before anything else)

You are given UPSTREAM CONTEXT below: the topic this moment sits inside,
why it was picked, and a candidate title — all written by a reader who saw
the WHOLE talk, not just this clip. The clip transcript alone often hides
the speaker's intent. A line read literally can be the exact opposite of
what the speaker means.

Before you title anything, decide the speaker's REGISTER from the context:
- sincere — says what they mean
- ironic / sarcastic — says the opposite of what they mean, often mocking
- joking — playing for a laugh, exaggerating
- provocative — overturning a common belief on purpose

If the moment is ironic or joking, a literal restatement of the words is
WRONG — it ships the joke as if it were earnest and reads as the pipeline
not understanding the clip. Title the speaker's actual POINT (and, when it
fits, the humor), not the surface words. Example failure: a speaker mocking
abstraction-obsessed programmers by listing what he "refuses to think
about" is NOT confessing — titling it "WHAT GREAT ENGINEERS REFUSE TO
THINK ABOUT" inverts his meaning. The topic ("loves Go's simplicity")
makes the real point obvious.

Treat the candidate title as a starting point to sharpen, not gospel —
keep it if it nails the point, replace it if you can hook harder. Use the
context only to UNDERSTAND; never put topic/rationale wording in the title
verbatim, and the cold-viewer test below still applies.

"""

print(f"""You are writing the TITLE CARD text for a short-form vertical video clip.

The title pops in on the first ~2.5s over the clip's opening frames. It is
the FIRST thing a scrolling stranger sees. They have no context about the
source video, the channel, or the topic. Many of them are watching with
audio muted for the first second. The title must work as a silent visual
hook on its own.

## What the title does

The title LOADS A DEBT that the clip PAYS. It promises one specific
moment, reveal, fact, or contradiction inside the clip. Done right, a
viewer who would have swiped past now holds still to find out what the
title was pointing at.

But a debt nobody understands is no hook. These clips are pulled OUT OF
CONTEXT from a long talk, so the title is the only thing telling a
stranger what this moment is even about. The title must convey the clip's
actual POINT — the message, finding, or claim a viewer would walk away
with — not just gesture vaguely at it. Withhold the precise punchline (the
exact number, name, or final word), NOT the subject and stakes of the
clip. "WHAT GOLD STARS DID TO THESE KIDS" fails: it hides the entire point
behind "WHAT...DID" and "THESE KIDS" means nothing to a stranger. State
the finding: rewards backfired, kids quit what they loved. Name the real
thing, surface the real consequence, hold back only the precise figure.

{step0}## Step 1 — analyze the clip

Read the transcript below. Decide if the clip has a single clear PAYOFF:
- A reveal (a surprising number, fact, name, outcome)
- A punchline near the end
- A contradiction's resolution
- A reaction or moment the rest of the clip builds toward

Identify the clip's human SUBJECT and NAME them. The speaker is almost
always the person named in the source metadata below — derive their short
familiar name from the source video title / uploader (e.g. source title
"Caseoh | Jynxzi Podcast #1" → "CASEOH"; "Speed" not "IShowSpeed"; first
name only when obvious). If the clip is ABOUT a different named person,
use that name. The transcript itself often only says "I" / "he" — the
metadata is how you recover the real name. You MUST resolve every subject
to a proper name; a title may not fall back to a pronoun.

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

d. Result / consequence
   State what HAPPENED or what the finding WAS — the outcome the clip
   lands on. Use when the clip is an experiment, story, or cause→effect
   with a clear result. Name the cause and the kind of consequence
   without dropping the precise figure: "GOLD STARS MADE KIDS QUIT
   DRAWING" works; "WHAT GOLD STARS DID TO THESE KIDS" does not.

Pick the framing that conveys the clip's point most clearly to a
stranger. When in doubt, prefer the framing that states the most of the
message — under-explaining loses more viewers than mild spoiling.

## Step 3 — if no clear payoff exists

If the clip is continuous info with no discrete climax, or the
transcript is too sparse to identify a payoff, fall back to framing (a)
only — surface the single most surprising concrete claim. Do not invent
a payoff that is not in the transcript. Always emit a title — never
return empty.

## Hard rules

- THIRD PERSON ONLY. No "I", "me", "my", "we", "us", "our", "you",
  "your". Chyron voice.
- NO PRONOUNS STANDING IN FOR A PERSON. The title may not use "HE",
  "HIM", "HIS", "SHE", "HER", "HERS", "THEY", "THEM", "THEIR" as the
  ONLY reference to a person. Every person must be a PROPER NAME,
  recovered from the source metadata when the transcript only has a
  pronoun (see Step 1). "TWITCH CHECK MADE HIM QUIT" fails — write
  "TWITCH CHECK MADE CASEOH QUIT". The ONLY allowed pronoun is a
  possessive whose antecedent is ALREADY NAMED in the same title ("FANS
  SAY CASEOH SAVED THEIR LIVES" is fine — "THEIR" = the named FANS).
  Re-read your title before emitting and replace any person-pronoun that
  lacks a named antecedent.
- WITHHOLD THE PRECISE PUNCHLINE, NOT THE POINT. The title may not
  contain the exact punchline word, number, or named final outcome the
  clip is built around. If the clip's reveal is "octopuses have nine
  brains", the title may say octopuses have more brains than you'd think
  — but never "NINE". This is the ONLY thing you withhold. Do NOT hide
  the subject, the cause, or the kind of result behind empty
  constructions like "WHAT X DID" or "WHAT HAPPENED WHEN" — those
  withhold the whole message and fail the test below.
- COLD-VIEWER TEST. The title must make sense to someone who has never
  heard of the source video, channel, host, or topic. No referent that
  only existing viewers would understand.
- MESSAGE TEST. A stranger reading the title must be able to say what
  the clip is ABOUT and roughly what it claims — the point survives even
  with the precise figure held back. If the title would leave them
  guessing the subject (not just the answer), it fails. Self-check this
  before emitting.
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
- No demonstrative referents to unnamed groups or things: "THESE KIDS",
  "THESE PEOPLE", "THIS STUDY", "THIS EXPERIMENT", "THIS MAN". A
  stranger has no idea who/what they point to. Name the actual subject
  or describe it concretely instead ("KIDS WHO LOVED DRAWING", not
  "THESE KIDS").
- No empty-withholding shells: "WHAT X DID", "WHAT HAPPENED WHEN",
  "WHAT X REVEALED", "WHAT THEY FOUND". They hide the message instead
  of the punchline. State the finding.
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

Upstream context (for your understanding — NEVER shown to the viewer):
{ctx_block or "(none — judge tone from the clip transcript alone)"}

Clip transcript:
{body}

Reply with ONLY the title line. No quotes. No explanation. Just the
title.""")
