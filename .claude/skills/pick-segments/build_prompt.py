#!/usr/bin/env python3
# Build a compact prompt for Claude: transcript lines + RMS profile.
import json, sys

transcript_path, rms_path, n, dmin, dmax = sys.argv[1:6]
n, dmin, dmax = int(n), float(dmin), float(dmax)

tx = json.load(open(transcript_path))
rms = json.load(open(rms_path))

segments = tx.get("segments") or []
if not segments and tx.get("words"):
    # Fall back: bucket words into ~10s lines
    cur = []
    t0 = None
    for w in tx["words"]:
        if t0 is None:
            t0 = w["t0"]
        cur.append(w["w"])
        if w["t1"] - t0 >= 10:
            segments.append({"t0": t0, "t1": w["t1"], "text": " ".join(cur)})
            cur, t0 = [], None
    if cur:
        segments.append({"t0": t0 or 0, "t1": tx["words"][-1]["t1"], "text": " ".join(cur)})

duration = segments[-1]["t1"] if segments else rms.get("seconds", 0)

# RMS sparkline: bucket into ~60 bins
bins = []
vals = rms.get("rms", [])
if vals:
    nb = min(60, len(vals))
    step = len(vals) / nb
    for i in range(nb):
        a = int(i * step)
        b = max(a + 1, int((i + 1) * step))
        chunk = vals[a:b]
        bins.append(sum(chunk) / len(chunk))
    peak = max(bins) or 1.0
    bars = "▁▂▃▄▅▆▇█"
    spark = "".join(bars[min(7, int(v / peak * 7))] for v in bins)
else:
    spark = "(no audio energy data)"

lines = []
for s in segments:
    lines.append(f"[{s['t0']:.1f}-{s['t1']:.1f}] {s['text'].strip()}")
transcript_block = "\n".join(lines)

print(f"""You are picking clip-worthy spans for vertical shorts.

Source duration: {duration:.1f}s
Audio energy (per ~1s of source, bucketed to ~60 bins, ▁ low → █ high):
{spark}

Transcript (timestamped lines, seconds):
{transcript_block}

Pick {n} non-overlapping spans, each {dmin:.0f}-{dmax:.0f} seconds long, that would work as standalone shorts. Favor self-contained moments: a punchline, a reaction, a complete thought, a strong reveal. Avoid mid-sentence cuts.

Reply with ONLY a JSON object (no prose, no code fences):
{{"shorts": [{{"t0": <float>, "t1": <float>, "rationale": "<short reason>", "title_suggestion": "<short title>"}}]}}""")
