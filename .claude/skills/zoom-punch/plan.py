#!/usr/bin/env python3
# pick punch-in moments: loudest RMS seconds snapped to word starts.
# argv: transcript.json rms.json dur -> JSON list of times
import json, sys

tx_path, rms_path, dur = sys.argv[1], sys.argv[2], float(sys.argv[3])

words = json.load(open(tx_path)).get("words", [])
rms = json.load(open(rms_path)).get("rms", [])

LEAD = 2.8     # title card owns the open
TAIL = 2.0
SPACING = 4.0
k = max(1, min(4, int(dur / 12)))

ranked = sorted(
    (i for i in range(len(rms)) if LEAD <= i <= dur - TAIL),
    key=lambda i: -rms[i],
)

def snap(t):
    # nearest word start within 0.6s — the punch lands ON an emphasis word
    best = None
    for w in words:
        d = abs(float(w["t0"]) - t)
        if d <= 0.6 and (best is None or d < abs(best - t)):
            best = float(w["t0"])
    return best if best is not None else t

picks = []
for i in ranked:
    t = snap(i + 0.5)
    if t < LEAD or t > dur - TAIL:
        continue
    if any(abs(t - p) < SPACING for p in picks):
        continue
    picks.append(round(t, 3))
    if len(picks) >= k:
        break

json.dump(sorted(picks), sys.stdout)
