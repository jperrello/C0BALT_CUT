#!/usr/bin/env python3
# rebase: slice the whole-video transcript + speaker track down to one clip's
# [t0, t1] window and shift timestamps to clip-local time (starting at 0).
# Driver glue for shorts.sh — not an atomic skill.
import json, sys

transcript, speaker, t0, t1, out_tx, out_spk, clip = sys.argv[1:8]
t0, t1 = float(t0), float(t1)
dur = t1 - t0


def clamp(v):
    return max(0.0, min(dur, round(v, 3)))


tx = json.load(open(transcript))
words = []
for w in tx.get("words", []):
    if w["t1"] > t0 and w["t0"] < t1:
        words.append({"t0": clamp(w["t0"] - t0), "t1": clamp(w["t1"] - t0), "w": w["w"]})
segments = []
for s in tx.get("segments", []):
    if s["t1"] > t0 and s["t0"] < t1:
        segments.append({"t0": clamp(s["t0"] - t0), "t1": clamp(s["t1"] - t0), "text": s["text"]})
json.dump(
    {"source": clip, "language": tx.get("language", "en"), "words": words, "segments": segments},
    open(out_tx, "w"), indent=2,
)

spk = json.load(open(speaker))
spans = []
for s in spk.get("spans", []):
    if s["t1"] > t0 and s["t0"] < t1:
        spans.append({
            "t0": clamp(s["t0"] - t0),
            "t1": clamp(s["t1"] - t0),
            "speaker_box": s.get("speaker_box"),
            "confidence": s.get("confidence", "low"),
        })
json.dump({"source": clip, "spans": spans}, open(out_spk, "w"), indent=2)

print(f"rebase: {len(words)} words, {len(spans)} speaker spans", file=sys.stderr)
