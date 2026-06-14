#!/usr/bin/env python3
# Apply the completeness verdicts to segments.json. For needs_more_tail we
# extend the span's t1 (and the last cut's end) outward to extend_t1, but only
# when it is a genuine OUTWARD nudge that keeps the selected source within dmax.
# Everything else passes through unchanged with a completeness_verdict note.
import json, re, sys

reply_path, segments_path, dmax = sys.argv[1:4]
dmax = float(dmax)

doc = json.load(open(segments_path))
segs = doc.get("shorts", [])

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
        ok = (
            nt1 is not None
            and nt1 > end + 0.1                      # genuinely outward
            and selected + (nt1 - end) <= dmax + 0.5  # stays within budget
        )
        if ok:
            cuts[-1][1] = round(nt1, 2)
            s["cuts"] = cuts
            s["t1"] = round(cuts[-1][1], 2)
            s["completeness_note"] = f"Δt1=+{nt1 - end:.2f}; {s['completeness_note']}"
        else:
            s["completeness_verdict"] = "truncated"
            s["completeness_note"] = f"extend rejected (budget/boundary); {s['completeness_note']}"
    out.append(s)

json.dump({"source": doc.get("source", ""), "shorts": out}, sys.stdout, indent=2)
