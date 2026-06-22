#!/usr/bin/env python3
# Extract candidate clip-moments from an rlm segment-topics reply and write
# candidates.hint.json (consumed by pick-segments as a discovery HINT). Best
# effort: a reply with no candidates yields an empty hint, never an error.
#
# Two candidate shapes:
#   - simple : {t0,t1,quote,why,confidence}                       (one window)
#   - thread : {thread:true,kind,cuts:[[a,b],...],bridge,quote,why,confidence}
#              a cross-chunk stitch — setup in one place, payoff in another
#              (shorts-qw3). t0/t1 derive from the cut span.
# confidence (shorts-7mk) is the reduce's standalone-clip-worthiness score; it
# ranks the hints so pick-segments weights them instead of treating them flat.
import json, re, sys

reply_path, transcript_path = sys.argv[1:3]
tx = json.load(open(transcript_path))
segs = tx.get("segments") or []
duration = segs[-1]["t1"] if segs else 0

def clamp_conf(v):
    try:
        c = float(v)
    except (TypeError, ValueError):
        return 0.5
    return round(max(0.0, min(1.0, c)), 2)

def in_bounds(a, b):
    return b > a and a >= 0 and not (duration and b > duration + 5)

text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
cands = []
threads = 0
if m:
    try:
        clist = json.loads(m.group(0)).get("candidates", [])
        for c in (clist if isinstance(clist, list) else []):
            if not isinstance(c, dict):
                continue
            is_thread = bool(c.get("thread")) and isinstance(c.get("cuts"), list)
            if is_thread:
                cuts = []
                for r in c["cuts"]:
                    try:
                        a, b = float(r[0]), float(r[1])
                    except (TypeError, ValueError, IndexError):
                        continue
                    if in_bounds(a, b):
                        cuts.append([round(a, 2), round(b, 2)])
                cuts.sort(key=lambda r: r[0])
                # keep chronological, non-overlapping; need >=2 cuts to be a thread
                merged = []
                for a, b in cuts:
                    if not merged or a >= merged[-1][1]:
                        merged.append([a, b])
                if len(merged) < 2:
                    continue
                kind = str(c.get("kind", "")).strip().lower()
                if kind not in ("setup_payoff", "callback", "escalation", "contradiction"):
                    kind = "setup_payoff"
                cands.append({
                    "t0": merged[0][0],
                    "t1": merged[-1][1],
                    "thread": True,
                    "kind": kind,
                    "cuts": merged[:3],
                    "bridge": str(c.get("bridge", "")).strip()[:240],
                    "quote": str(c.get("quote", "")).strip()[:400],
                    "why": str(c.get("why", "")).strip()[:200],
                    "confidence": clamp_conf(c.get("confidence", 0.6)),
                })
                threads += 1
                continue
            t0 = float(c["t0"]); t1 = float(c["t1"])
            if not in_bounds(t0, t1):
                continue
            cands.append({
                "t0": round(t0, 2),
                "t1": round(t1, 2),
                "quote": str(c.get("quote", "")).strip()[:400],
                "why": str(c.get("why", "")).strip()[:200],
                "confidence": clamp_conf(c.get("confidence", 0.5)),
            })
    except (ValueError, KeyError, TypeError, AttributeError):
        cands = []
        threads = 0

# Rank by confidence (desc) so pick-segments surfaces the strongest hints first;
# threads tie-break above simple candidates of equal confidence, then by t0.
cands.sort(key=lambda c: (-c["confidence"], not c.get("thread"), c["t0"]))
json.dump({"source": tx.get("source", ""), "n_threads": threads, "candidates": cands},
          sys.stdout, indent=2)
