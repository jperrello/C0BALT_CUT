---
name: generate-title
description: Generate a per-clip third-person engagement-driven title card text. Claude reads the clip's transcript plus the source video's ingest.json metadata, infers the subject, and emits a hook-driven ALL-CAPS title (<=7 words). Replaces pick-segments' title_suggestion.
allowed-tools: Bash
user-invocable: true
---

# generate-title

One title per clip. Third-person, names the subject, promises a specific
moment, ALL CAPS, ≤7 words. Designed for the title-transition skill.

## Invoke

```
.claude/skills/generate-title/generate-title.sh <clip_transcript.json> <ingest.json> <out.txt>
```

- `clip_transcript`: clip-local transcript with `words[]` and/or `segments[]`
- `ingest`: the source video's ingest.json (provides title, uploader, url —
  helps name the subject when the transcript doesn't say it explicitly)
- `out`: text file with the title (single line, ALL CAPS, ≤7 words)

## Output

A single-line text file. Example contents:

```
WATCH SPEED RAGE AT STREAM SNIPERS
```

## Prompt principles (enforced)

- Third person — never "I", "me", "my", "we".
- Name the subject (inferred from clip transcript + ingest.json).
- Promise ONE specific moment, behavior, or reaction — not a vague topic.
- ≤7 words, ALL CAPS, no emoji, no clickbait punctuation (no "?" / "!" / "..." / quotes).
- No "Watch X..." filler when it doesn't add a hook; only use opener verbs
  when they sharpen the promise.

## Fallback

If `claude -p` fails or the model returns something unusable (empty, >7 words,
contains banned punctuation), `parse_reply.py` falls back to the first 5
non-filler words from the clip transcript, uppercased.
