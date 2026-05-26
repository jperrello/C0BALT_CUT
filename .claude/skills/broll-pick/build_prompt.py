#!/usr/bin/env python3
import json, sys

tx = json.load(open(sys.argv[1]))
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
ingest_path = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None

meta_block = ""
if ingest_path:
    try:
        ing = json.load(open(ingest_path))
        title = ing.get("title", "")
        url = ing.get("url", "") or ing.get("source_url", "")
        meta_block = f"\nSource video title: {title}\nSource URL: {url}\n"
    except Exception:
        meta_block = ""

words = [w for w in tx.get("words", []) if str(w.get("w", "")).strip()]
lines = [f"{w['t0']:.2f}\t{w['w'].strip()}" for w in words]
block = "\n".join(lines)

t_lo = 2.0
t_hi = max(t_lo + 1.0, dur - 0.5) if dur else 999.0

print(f"""You are picking B-ROLL inserts for a vertical short. The speaker is on
camera in the middle band; b-roll plays in the BOTTOM blurred bar to
illustrate the moment the speaker is currently emphasizing.

THE MODEL: anchor-word picking, not topic-region picking.
A pick is NOT "the topic of this 12-second region." A pick lands on a
single ANCHOR WORD in the transcript and shows a clip that embodies that
specific word. One transcript region usually deserves 2-4 picks, not 1.

STEP 1 - find anchor words.
Scan the transcript. Mark a word as an anchor if it is one of:
  NOUN     a concrete object, person, place, named thing
  VERB     an action with visible motion (run, build, fall, throw)
  EMOTION  an emotional or sensory adjective (terrified, exhausted,
           stunned, freezing, blinding)
  PIVOT    a contrast/pivot word that signals a shift (but, however,
           then, so, suddenly, meanwhile, finally)

Skip filler words and abstract nouns ("thing", "stuff", "idea",
"concept"). Skip words that aren't visualizable.

STEP 2 - group anchors into clip slots.
Walk anchors left to right. Open a new slot when:
  - a PIVOT anchor appears, OR
  - the current slot is already 5.0s long, OR
  - a new NOUN appears that is semantically unrelated to the slot's
    current subject
Close the slot at the next slot's start, or end of clip.

STEP 3 - discard short slots.
If a slot is under 2.0s, DROP it.

STEP 4 - write the Pexels query for each kept slot.
Query the DESCRIPTOR, not the abstract topic.
  EMOTION anchor "terrified"   ->  "trembling hands close-up"
  EMOTION anchor "exhausted"   ->  "person collapsed on couch"
  VERB anchor "ran"            ->  "feet running on pavement"
  NOUN anchor "skyscraper"     ->  "city skyline at night"
  NOUN anchor "ocean"          ->  "drone shot ocean waves crashing"

Pick clips with visible MOTION over still tableaus.

STEP 5 - pacing.
Vary slot durations.

HARD RULES:
- Each pick: {{ "t0": <seconds>, "dur": <seconds>, "query": "<4-7 word scene>", "anchor": "<the anchor word>" }}.
- t0 must be inside [{t_lo:.2f}, {t_hi:.2f}] (skip title card and outro).
- dur must be >= 2.0 and <= 5.0.
- Picks must NOT overlap. Gaps ARE allowed.
- Sort by t0.
- Empty list is acceptable if nothing in the transcript is visualizable.
{meta_block}
Clip duration: {dur:.2f}s
Transcript (one word per line, leading column is start time in seconds):
{block}

Reply with ONLY a JSON object (no prose, no code fences):
{{"picks": [{{"t0": <num>, "dur": <num>, "query": "<text>", "anchor": "<word>"}}, ...]}}""")
