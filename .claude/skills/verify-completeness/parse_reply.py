#!/usr/bin/env python3
# Apply the completeness verdicts to segments.json. For needs_more_tail we
# extend the span's t1 (and the last cut's end) outward to extend_t1, but only
# when it is a genuine OUTWARD nudge that keeps the selected source within dmax.
# Everything else passes through unchanged with a completeness_verdict note.
import json, re, sys

reply_path, segments_path, dmax = sys.argv[1:4]
tx_path = sys.argv[4] if len(sys.argv) > 4 else None
dmax = float(dmax)

doc = json.load(open(segments_path))
segs = doc.get("shorts", [])

# Sentence-boundary ends from the source transcript: the t1 of every word whose
# text ends in . ? or ! — the only points an outward nudge may land on, so the
# clip never ends mid-sentence (the "maybe a billion," truncation bug).
boundaries = []
if tx_path:
    try:
        words = json.load(open(tx_path)).get("words", [])
        boundaries = sorted(w["t1"] for w in words if str(w.get("w", "")).strip()[-1:] in ".?!")
    except (OSError, ValueError, KeyError, TypeError):
        boundaries = []

def snap(end, target):
    # Largest sentence boundary in (end, target]; None if no clean landing exists.
    cands = [b for b in boundaries if end + 0.1 < b <= target + 0.5]
    return max(cands) if cands else None

text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
verdicts = {}
if m:
    try:
        verdicts = {int(v["span"]): v for v in json.loads(m.group(0)).get("verdicts", [])}
    except (ValueError, KeyError, TypeError):
        verdicts = {}

out = []
for i, s in enumerate(segs):
    s = dict(s)
    v = verdicts.get(i)
    if v is None:
        s["completeness_verdict"] = "complete"
        s["completeness_note"] = "no verdict; passthrough"
        out.append(s)
        continue
    verdict = str(v.get("verdict", "complete"))
    s["completeness_verdict"] = verdict
    s["completeness_note"] = str(v.get("note", ""))[:160]
    if verdict == "needs_more_tail":
        cuts = s.get("cuts") or [[s["t0"], s["t1"]]]
        end = cuts[-1][1]
        selected = sum(b - a for a, b in cuts)
        try:
            nt1 = float(v.get("extend_t1"))
        except (TypeError, ValueError):
            nt1 = None
        # Snap the requested landing DOWN to the last complete sentence at or
        # before extend_t1 — never extend to a mid-sentence point (a partway
        # nudge that ends mid-clause is strictly worse than a clean stop).
        snapped = snap(end, nt1) if (nt1 is not None and boundaries) else nt1
        ok = (
            snapped is not None
            and snapped > end + 0.1                       # genuinely outward
            and selected + (snapped - end) <= dmax + 0.5  # stays within budget
        )
        if ok:
            cuts[-1][1] = round(snapped, 2)
            s["cuts"] = cuts
            s["t1"] = round(cuts[-1][1], 2)
            s["completeness_note"] = f"Δt1=+{snapped - end:.2f}; {s['completeness_note']}"
        else:
            s["completeness_verdict"] = "truncated"
            s["completeness_note"] = f"extend rejected (no clean landing within budget); {s['completeness_note']}"
    out.append(s)

json.dump({"source": doc.get("source", ""), "shorts": out}, sys.stdout, indent=2)
