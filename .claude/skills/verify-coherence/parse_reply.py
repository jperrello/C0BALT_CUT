#!/usr/bin/env python3
import json, re, sys

reply_path, segments_path, dmin = sys.argv[1:4]
dmin = float(dmin)

segs_doc = json.load(open(segments_path))
segs = segs_doc.get("shorts", [])

text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
if not m:
    print(f"verify-coherence: no JSON in reply: {text!r}", file=sys.stderr)
    sys.exit(1)
data = json.loads(m.group(0))

verdicts = {int(v["span"]): v for v in data.get("verdicts", [])}

out = []
for i, s in enumerate(segs):
    v = verdicts.get(i)
    if v is None or v.get("action") == "keep":
        s = dict(s)
        s["coherence_verdict"] = "keep"
        out.append(s)
        continue
    t0 = float(v.get("t0", s["t0"]))
    t1 = float(v.get("t1", s["t1"]))
    if t1 <= t0 or (t1 - t0) < dmin:
        print(f"verify-coherence: dropping span {i} (tightened to {t0:.1f}-{t1:.1f} < dmin {dmin})",
              file=sys.stderr)
        continue
    if t0 < s["t0"] - 0.5 or t1 > s["t1"] + 0.5:
        print(f"verify-coherence: span {i} tighten range {t0:.1f}-{t1:.1f} outside original; keeping",
              file=sys.stderr)
        s = dict(s)
        s["coherence_verdict"] = "keep"
        out.append(s)
        continue
    s = dict(s)
    s["t0"] = round(t0, 2)
    s["t1"] = round(t1, 2)
    s["coherence_verdict"] = "tightened"
    s["coherence_note"] = str(v.get("note", ""))[:200]
    out.append(s)

json.dump({"source": segs_doc.get("source", ""), "shorts": out}, sys.stdout, indent=2)
