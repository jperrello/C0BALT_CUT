#!/usr/bin/env python3
# Plan timeline-preserving reframe cuts: tile [0,dur] into segments that
# alternate a base framing with tighter punch-ins, each boundary snapped to a
# word start so the cut lands on speech. Deterministic — no Claude.
# argv: transcript.json dur  ->  {"segs":[{t0,t1,level}], "punch":[[scale,xf,yf]]}
import json, math, os, sys

tx_path, dur = sys.argv[1], float(sys.argv[2])
words = json.load(open(tx_path)).get("words", []) if tx_path and os.path.exists(tx_path) else []

LEAD = float(os.environ.get("JUMP_CUT_LEAD", "2.6"))   # cold-open title owns a stable shot
TAIL = float(os.environ.get("JUMP_CUT_TAIL", "1.5"))   # stable landing
SEG = float(os.environ.get("JUMP_CUT_SEG", "3.2"))     # target segment length (cut rhythm)
MIN_DUR = float(os.environ.get("JUMP_CUT_MIN", "13.0"))
MAX_GAP = float(os.environ.get("JUMP_CUT_MAX_GAP", "5.0"))  # no static stretch may exceed this
SNAP = 0.7

# Cut count is driven by COVERAGE, not a fixed cap: place enough cuts to churn
# the WHOLE body at `step` cadence so a long clip never trails off into a static
# tail (the 18.8s-tail bug — old JUMP_CUT_MAX=8 stopped cutting at ~28s on a 47s
# clip). step honors MAX_GAP even when SEG is widened. JUMP_CUT_MAX, when set,
# stays an explicit hard ceiling (back-compat); unset = cover the clip. _safety
# guards the filter graph against pathological inputs.
step = min(SEG, MAX_GAP) if SEG > 0 else SEG
_hard_cap = os.environ.get("JUMP_CUT_MAX")
_safety = 24

# punch levels: (scale, x_frac, y_frac) — crop top-left as a fraction of slack.
# centered horizontally, biased to the upper third so the eyeline holds.
PUNCH = [(1.16, 0.5, 0.34), (1.11, 0.5, 0.34)]


def snap(t):
    best = None
    for w in words:
        d = abs(float(w["t0"]) - t)
        if d <= SNAP and (best is None or d < abs(best - t)):
            best = float(w["t0"])
    return best if best is not None else t


segs = []
if dur >= MIN_DUR and step > 0:
    body = dur - LEAD - TAIL
    maxcuts = int(_hard_cap) if _hard_cap else math.ceil(body / step) + 1
    maxcuts = max(0, min(maxcuts, _safety))
    cuts, t = [], LEAD + step
    while t < dur - TAIL - 0.6 and len(cuts) < maxcuts:
        p = round(snap(t), 3)
        if LEAD + 0.4 < p < dur - TAIL - 0.4 and (not cuts or p - cuts[-1] >= 1.6):
            cuts.append(p)
        t += step
    bounds = [0.0] + cuts + [dur]
    nseg = len(bounds) - 1
    pi = 0
    for i in range(nseg):
        a, b = bounds[i], bounds[i + 1]
        if b - a < 0.4:
            continue
        punch = (i % 2 == 1) and i != nseg - 1   # odd interior segs punch; first + last stay base
        if punch:
            lvl = 1 + (pi % len(PUNCH))
            pi += 1
        else:
            lvl = 0
        segs.append({"t0": round(a, 3), "t1": round(b, 3), "level": lvl})
    if not any(s["level"] for s in segs):   # nothing to cut -> passthrough
        segs = []

json.dump({"dur": dur, "punch": PUNCH, "segs": segs}, sys.stdout)
