#!/usr/bin/env python3
# Build a compact prompt for Claude: transcript lines + RMS profile.
import json, sys

transcript_path, rms_path, n, dmin, dmax = sys.argv[1:6]
topics_path = sys.argv[6] if len(sys.argv) > 6 else ""
n, dmin, dmax = int(n), float(dmin), float(dmax)

tx = json.load(open(transcript_path))
rms = json.load(open(rms_path))
topics = []
if topics_path:
    try:
        topics = json.load(open(topics_path)).get("topics", [])
    except FileNotFoundError:
        topics = []

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

if topics:
    topic_block = "\n".join(
        f"  topic {i+1} [{t['t0']:.1f}-{t['t1']:.1f}] {t.get('title','')}: {t.get('summary','')}"
        for i, t in enumerate(topics)
    )
    topic_rules = f"""
TOPIC BOUNDARIES (HARD CONSTRAINT):
{topic_block}

Each picked span MUST lie entirely within ONE topic — never straddle a boundary. A short that crosses topics reads as two unrelated clips spliced together; that is the failure mode we are explicitly preventing. If a topic is shorter than {dmin:.0f}s, skip it. You do not need to pick from every topic; pick the {n} strongest single-topic moments overall.
"""
else:
    topic_rules = ""

print(f"""You are picking clip-worthy spans for vertical shorts.

Source duration: {duration:.1f}s
Audio energy (per ~1s of source, bucketed to ~60 bins, ▁ low → █ high):
{spark}

Transcript (timestamped lines, seconds):
{transcript_block}
{topic_rules}
Pick {n} non-overlapping spans, each {dmin:.0f}-{dmax:.0f} seconds long, that would work as standalone shorts. Avoid mid-sentence cuts.

SCROLL-STOP HOOK (highest priority — shorts that don't grab in the first 1-2s are dead):
You are picking the spans a viewer is LEAST likely to scroll past and MOST likely to finish. The OPENING WORDS of each span are what a viewer sees first. Score each pick on:
  - hook_score (0-10): does the first 1-2s plant a curiosity question OR land a striking visual/factual claim? Reward concrete nouns, numbers, named subjects, surprising statements, direct questions. Punish vague setup.
  - structure_score (0-10): does the span have hook → foreshadow → payoff? Is there but/therefore causality between beats (not just "and then")? Does it open a curiosity loop that resolves by the end?
  - overall_score (0-10): your holistic rank — would you stop scrolling AND watch to the end? Weigh what tends to make a span engaging: high vocal energy/affect (excitement, laughter, emphasis), lively back-and-forth exchange, and concrete/specific nouns and real stakes. Read the RMS sparkline above as an affect cue — favor spans sitting over energy peaks (laughter, raised voices), not flat valleys. These are examples of engagement, not a checklist: a gripping span missing some still ranks high.

HARD REJECT — do NOT pick spans whose first transcript word is filler:
  so, and, but, um, uh, like, well, okay, ok, basically, actually, anyway, you know, I mean, I think, I guess, kind of, sort of
Trim the span start forward to a stronger opening word if needed (still respect {dmin:.0f}s minimum).

Reply with ONLY a JSON object (no prose, no code fences):
{{"shorts": [{{"t0": <float>, "t1": <float>, "rationale": "<short reason>", "title_suggestion": "<short title>", "hook_score": <0-10>, "structure_score": <0-10>, "overall_score": <0-10>}}]}}""")
