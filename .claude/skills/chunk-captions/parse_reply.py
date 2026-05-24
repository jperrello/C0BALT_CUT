#!/usr/bin/env python3
import json, re, sys

reply_path, transcript_path = sys.argv[1:3]

tx = json.load(open(transcript_path))
words = [w for w in tx.get("words", []) if str(w.get("w", "")).strip()]
N = len(words)

def fallback():
    out = []
    i = 0
    step = 5
    while i < N:
        idxs = list(range(i, min(i + step, N)))
        out.append(idxs)
        i += step
    return out

text = open(reply_path).read() if reply_path != "-" else ""
groups = None
if text:
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            raw = data.get("chunks", [])
            cand = []
            seen = set()
            ok = True
            last = -1
            for g in raw:
                idxs = [int(x) for x in g if isinstance(x, (int, float, str)) and str(x).lstrip("-").isdigit()]
                idxs = [i for i in idxs if 0 <= i < N]
                if not idxs:
                    continue
                idxs.sort()
                if idxs[0] <= last:
                    ok = False; break
                if any(i in seen for i in idxs):
                    ok = False; break
                seen.update(idxs)
                last = idxs[-1]
                cand.append(idxs)
            if ok and len(seen) == N:
                groups = cand
        except Exception:
            groups = None

if groups is None:
    print("chunk-captions: reply invalid or incomplete; using fallback grouping", file=sys.stderr)
    groups = fallback()

chunks = []
for idxs in groups:
    ws = [words[i] for i in idxs]
    chunks.append({
        "text": " ".join(str(w["w"]).strip() for w in ws),
        "t0": round(float(ws[0]["t0"]), 3),
        "t1": round(float(ws[-1]["t1"]), 3),
        "words": [{"w": str(w["w"]).strip(),
                    "t0": round(float(w["t0"]), 3),
                    "t1": round(float(w["t1"]), 3)} for w in ws],
    })

json.dump({"source": tx.get("source", ""), "chunks": chunks}, sys.stdout, indent=2)
