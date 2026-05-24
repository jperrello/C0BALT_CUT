#!/usr/bin/env python3
import json, sys

tx = json.load(open(sys.argv[1]))
words = [w for w in tx.get("words", []) if str(w.get("w", "")).strip()]

lines = []
for i, w in enumerate(words):
    lines.append(f"{i}\t{w['w'].strip()}\t({w['t0']:.2f}-{w['t1']:.2f})")
block = "\n".join(lines)

print(f"""You are chunking spoken words into PHRASE-SIZED CAPTION GROUPS for short-form video subtitles.

Each chunk is what one breath / one clause would naturally hold. Typically 3-6
words. Avoid 1-word chunks (too flickery) and avoid >8-word chunks (too dense).
Break on natural clause boundaries: after subjects, after verbs, before
conjunctions ("and / but / so / because"), before relative clauses, at
punctuation.

Example:
  Spoken: "I saw a car today and it was red"
  Chunks: ["I saw a car today", "and it was red"]

Constraints:
- Every word index 0..{len(words)-1} MUST appear in exactly one chunk.
- Word indices within a chunk MUST be contiguous and increasing.
- Chunks MUST be in source order.

Words (index, word, time):
{block}

Reply with ONLY a JSON object (no prose, no code fences):
{{"chunks": [[<word_indices>], [<word_indices>], ...]}}
Each inner list is the indices for one chunk, in order.""")
