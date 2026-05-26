#!/usr/bin/env python3
import json, sys

tx = json.load(open(sys.argv[1]))
words = tx.get("words", [])

lines = []
for i, w in enumerate(words):
    lines.append(f"{i}\t{w['t0']:.2f}\t{w['t1']:.2f}\t{w['w']}")
body = "\n".join(lines)

print(f"""You are editing a podcast short. Below is a word-level transcript of ONE clip. Each line is:
<index>\\t<t0>\\t<t1>\\t<word>

Be AGGRESSIVE. Today's edits are too conservative — leave the speaker's point intact, but cut everything that doesn't serve it. The downstream verifier will catch over-trimming if it happens.

ALWAYS-REMOVABLE filler (no judgment call — if these tokens appear and are not load-bearing, REMOVE them):
- "um", "uh", "er", "ah", "hmm"
- "like" used as filler (not the verb / preposition)
- "you know", "I mean", "sort of", "kind of", "basically"
- audible non-speech tokens transcribed as words ("haha", "ahem")

COLLAPSE REPEATED RE-STARTS:
If the speaker restarts the same sentence 2+ times ("I went to — I went to the store" or "the thing is — the thing — the thing is we were late"), keep ONLY the LAST take. Remove every prior false start in that chain.

AGGRESSIVELY REMOVE digressive asides:
Any inter-sentence aside that doesn't reinforce the clip's dominant topic should be cut — even if it's grammatical. The clip is short; every second must push the main thought forward.

ALSO cut:
- trail-offs ("I was — yeah anyway")
- false starts that don't resolve

Keep:
- every word that delivers the main point
- proper nouns, numbers, the actual content
- one beat of natural rhythm at sentence boundaries (don't pack words wall-to-wall)

Return ONLY a JSON object on a single line:
{{"remove": [[start_idx, end_idx], ...], "notes": "..."}}

Ranges are INCLUSIVE on both ends and refer to the <index> column above. If nothing should be cut, return {{"remove": [], "notes": "clean"}}. Do not include any prose outside the JSON.

TRANSCRIPT:
{body}
""")
