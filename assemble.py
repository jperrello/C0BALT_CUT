#!/usr/bin/env python3
# assemble: build one clip-local transcript from MULTIPLE source cuts joined
# end-to-end (multi-cut story assembly). Mirrors rebase.py's output shape so
# every downstream skill (trim-filler, tighten-pace, captions, …) is unchanged.
# Driver glue for shorts.sh — not an atomic skill.
import json, sys

transcript, cuts_json, out_tx, clip = sys.argv[1:5]
cuts = json.loads(cuts_json)
tx = json.load(open(transcript))

words, segments = [], []
off = 0.0
for a, b in cuts:
    span = b - a

    def loc(v):
        return round(max(0.0, min(span, v - a)) + off, 3)

    for w in tx.get("words", []):
        if w["t1"] > a and w["t0"] < b:
            words.append({"t0": loc(w["t0"]), "t1": loc(w["t1"]), "w": w["w"]})
    for s in tx.get("segments", []):
        if s["t1"] > a and s["t0"] < b:
            segments.append({"t0": loc(s["t0"]), "t1": loc(s["t1"]), "text": s["text"]})
    off += span

json.dump(
    {"source": clip, "language": tx.get("language", "en"), "words": words, "segments": segments},
    open(out_tx, "w"), indent=2,
)
print(f"assemble: {len(words)} words from {len(cuts)} cuts", file=sys.stderr)
