#!/usr/bin/env python3
# apply claude's bookend adjustments to segments.json. clamp to the original
# ±extend window; if the new range collapses below dmin, keep the original.
import json, re, sys

reply_path, segments_path, extend, dmin = sys.argv[1:5]
extend = float(extend)
dmin = float(dmin)

doc = json.load(open(segments_path))
segs = doc.get("shorts", [])

text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
if not m:
    print(f"bookend-trim: no JSON in reply: {text!r}", file=sys.stderr)
    sys.exit(1)
adjustments = {int(a["span"]): a for a in json.loads(m.group(0)).get("adjustments", [])}

out = []
for i, s in enumerate(segs):
    s = dict(s)
    a = adjustments.get(i)
    if a is None:
        s["bookend_note"] = "no adjustment"
        out.append(s)
        continue
    try:
        nt0 = float(a["t0"])
        nt1 = float(a["t1"])
    except (KeyError, TypeError, ValueError):
        s["bookend_note"] = "parse error"
        out.append(s)
        continue
    if nt0 < s["t0"] - extend - 0.5 or nt1 > s["t1"] + extend + 0.5:
        s["bookend_note"] = f"out-of-window {nt0:.2f}-{nt1:.2f}; kept original"
        out.append(s)
        continue
    if nt1 - nt0 < max(dmin, 5.0):
        s["bookend_note"] = f"collapsed to {nt1 - nt0:.1f}s; kept original"
        out.append(s)
        continue
    d0 = nt0 - s["t0"]
    d1 = nt1 - s["t1"]
    s["t0"] = round(nt0, 2)
    s["t1"] = round(nt1, 2)
    # keep the multi-cut envelope consistent: snap the first cut's start and the
    # last cut's end to the new boundaries (only when the cut stays valid).
    cuts = s.get("cuts")
    if isinstance(cuts, list) and cuts:
        if nt0 < cuts[0][1]:
            cuts[0][0] = round(nt0, 2)
        if nt1 > cuts[-1][0]:
            cuts[-1][1] = round(nt1, 2)
    s["bookend_note"] = f"Δt0={d0:+.2f} Δt1={d1:+.2f}; {str(a.get('note',''))[:120]}"
    out.append(s)

json.dump({"source": doc.get("source", ""), "shorts": out}, sys.stdout, indent=2)
