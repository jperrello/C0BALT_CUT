#!/usr/bin/env python3
# Build a compact prompt for Claude: transcript lines + RMS profile.
import json, sys

transcript_path, rms_path, n, dmin, dmax = sys.argv[1:6]
topics_path = sys.argv[6] if len(sys.argv) > 6 else ""
heatmap_path = sys.argv[7] if len(sys.argv) > 7 else ""
hint_path = sys.argv[8] if len(sys.argv) > 8 else ""
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

# Most-replayed sparkline: YouTube's crowd-sourced replay graph for the SOURCE
# video — the sections real viewers rewatched. Same 60-bin render as RMS.
replay = ""
if heatmap_path:
    try:
        hm = json.load(open(heatmap_path)).get("heatmap", [])
    except (FileNotFoundError, ValueError):
        hm = []
    if hm and duration:
        bars = "▁▂▃▄▅▆▇█"
        nb = 60
        acc = [0.0] * nb
        cnt = [0] * nb
        for p in hm:
            mid = (float(p["start_time"]) + float(p["end_time"])) / 2
            i = min(nb - 1, max(0, int(mid / duration * nb)))
            acc[i] += float(p["value"])
            cnt[i] += 1
        vals = [a / c if c else 0.0 for a, c in zip(acc, cnt)]
        peak = max(vals) or 1.0
        replay = "".join(bars[min(7, int(v / peak * 7))] for v in vals)

replay_block = ""
if replay:
    replay_block = f"""
Most-replayed (YouTube's replay heatmap for this source — moments viewers rewatched, ▁ cold → █ hot):
{replay}

Use replay as a DISCOVERY HINT, not a decision rule. Replay peaks often mark the most surprising sentence inside a larger explanation; the short still needs enough setup before the peak and enough aftermath after it to make sense to someone who did not watch the full video. Never pick an isolated highlight just because it sits on a replay peak.
"""

# rlm candidate-moment hints (full-resolution per-chunk discovery) — surfaces
# back-half arcs the compressed transcript view can miss. HINT only.
hint_block = ""
if hint_path:
    try:
        cands = json.load(open(hint_path)).get("candidates", [])
    except (FileNotFoundError, ValueError):
        cands = []
    if cands:
        rows = "\n".join(
            f"  [{c['t0']:.1f}-{c['t1']:.1f}] {str(c.get('quote','')).strip()[:160]}"
            for c in cands
        )
        hint_block = f"""
CANDIDATE MOMENTS (rlm discovery hint — clip-worthy beats surfaced from a full-resolution per-chunk read; especially useful for the back half of long videos):
{rows}

Treat these as DISCOVERY HINTS only, exactly like the replay graph: they point you at moments worth examining, but YOUR standalone-arc judgment still decides. Expand any hint you use to a complete setup → turn → landing arc; never pick a bare quote because it appears here.
"""

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
{replay_block}
Transcript (timestamped lines, seconds):
{transcript_block}
{topic_rules}{hint_block}
Pick {n} non-overlapping shorts, each {dmin:.0f}-{dmax:.0f} seconds of SOURCE story selected, that would work as standalone shorts. Avoid mid-sentence cuts.

SELECTION BUDGET vs DELIVERED LENGTH (read this): the {dmin:.0f}-{dmax:.0f}s window is how much SOURCE story you select — NOT the final runtime. After you pick, downstream editing (filler removal + pace tightening) shaves roughly 20-30% of the dead air and trail-offs. So select the FULLER arc — include the complete setup and the landing — and trust the editor to tighten it into the ~30-40s sweet spot. Do NOT pre-trim the arc to hit a short target; an arc that already feels minimal at selection will land truncated after tightening.

STANDALONE CONTEXT (hard priority):
A good pick must make sense to a cold viewer with no surrounding podcast context. It needs:
  - setup: enough premise for the viewer to know what question/problem/example is being discussed.
  - turn: the surprising claim, conflict, demonstration, or insight.
  - landing: the speaker's explanation of why the turn matters, not just the last shocking phrase.

Reject a span if it is merely a highlight, definition, example, punchline, or replay spike without the surrounding thought. It is better to choose a less flashy topic with a complete arc than a hotter moment that ends abruptly. For long-form explainers and interviews, prefer 40-55 seconds of source when that is what the idea needs; use the minimum length only when the whole idea truly lands in less.

ASSEMBLE THE STORY WITH CUTS (important): a great short is EDITED, not just a raw clip. Each short is built from 1-3 source segments ("cuts") joined end-to-end. Most strong moments are a single continuous cut. But when the best version of a story has a slow middle, a tangent, or dead setup between two strong beats, SPLIT it: keep the gripping setup, CUT OUT the sag, and jump to the payoff — so the viewer gets a tight, complete arc instead of a thin skeleton or a meandering clip. Think like an editor assembling the most engaging 40-55s of source, not a knife making one slice.
  - Provide "cuts": a list of [start, end] source-second ranges, in chronological order, non-overlapping. The cuts play back-to-back.
  - ALL cuts of one short MUST stay within ONE topic — you are tightening a single story, never splicing two unrelated ones.
  - The SUM of cut durations must be {dmin:.0f}-{dmax:.0f}s. Keep cuts to 1-3; don't over-chop.
  - t0 = first cut's start, t1 = last cut's end.
  - A single-cut short is just "cuts": [[t0, t1]] — that's fine and common.
  - QUESTION-LEAD ASSEMBLY: a cold viewer stops for a hook they instantly get (see COLD-OPEN HOOK below). If the best arc's payoff is strong but its natural opening is slow, make your FIRST cut a short question or provocation pulled from EARLIER in the SAME topic that sets up exactly this payoff, then cut straight to the payoff. The lead-in must be about the same thing — you are restoring the Q→A the edit lost, never bolting on an unrelated question — and must occur earlier in the source than the payoff (cuts always play in source-chronological order).

COLD-OPEN HOOK (highest priority — shorts that don't grab in the first 1-2s are dead):
Frame 1 IS the hook — no preamble, no throat-clearing. The opening line is what a scrolling stranger sees and hears first (often muted). The strongest openings are understandable with ZERO context:
  - a QUESTION a stranger has also wondered ("How come I can see the moon during the day?", "What's more likely, teleportation or time travel?"),
  - a PROVOCATION / contrarian claim ("the richest women in the world — almost all of it is divorce money"),
  - or a striking, concrete factual claim with a named subject or a number.
PREFER spans whose literal first sentence is already one of these; use QUESTION-LEAD ASSEMBLY (above) when the payoff is great but its natural open is weak. Score each pick on:
  - hook_score (0-10): does the FIRST 1-2s land one of the three openings above for a cold viewer? Reward direct questions, contrarian provocations, concrete nouns, numbers, named subjects. Punish vague setup, pronouns with no referent, and slow throat-clearing.
  - context_score (0-10): can a cold viewer understand the setup, the turn, and why the ending matters without the surrounding sentences? Penalize abrupt endings hard.
  - structure_score (0-10): does the span have hook → foreshadow → payoff → landing, with but/therefore causality between beats (not just "and then")? Does it open a curiosity loop that resolves by the end?
  - hook_payoff_coherence (0-10): does the cold-open hook ACTUALLY pay off inside this span? A 10 means the opening question/provocation/claim is directly answered, resolved, or delivered on by the turn and landing. Score LOW when the open is bait that never lands — a juicy first line whose promise the rest of the span never honors, or a turn about something other than what the hook set up. This is the anti-clickbait term: reward openings whose curiosity loop closes; punish bait-and-switch.
  - payoff_offset_sec (0..span_len): seconds from the DELIVERED span start to the exact line where the turn/insight/payoff lands (the moment the curiosity loop starts resolving). 0 means the very first sentence is already the turn. THE TURN MUST LAND WITHIN ~3s OF THE DELIVERED OPEN — a payoff that lands 10s in is a setup-heavy bait-opener that loses the cold viewer before the reward. If the natural payoff is late but strong, use QUESTION-LEAD ASSEMBLY (above) to pull a short setup-question cut to the front so payoff_offset_sec stays small. Measure honestly against the cuts you chose: it is the offset within the assembled, delivered short, not the raw source.
  - overall_score (0-10): your holistic rank — would you stop scrolling AND watch to the end? Weigh complete standalone meaning first, then cold-open hook strength (PREFER open-loop question/provocation hooks over flat claims), then how fast the payoff lands, then vocal energy/affect, concrete stakes, RMS peaks, and replay peaks. RMS/replay can break ties but cannot rescue a confusing, abrupt, or slow-to-pay-off clip. (Note: the deterministic ranker recomputes the final 0-99 rank from your sub-scores — including hook_payoff_coherence and payoff_offset_sec — so rate every field honestly rather than gaming overall_score.)
Also report, for each pick:
  - opening_line: the verbatim first ~8-12 words a viewer hears (after any question-lead assembly).
  - hook_type: "question", "provocation", or "claim" — what that opening line is. PREFER open-loop "question" and "provocation" hooks (they create a curiosity gap a stranger needs filled) over flat "claim" hooks.

HARD REJECT — do NOT pick spans whose first transcript word is filler:
  so, and, but, um, uh, like, well, okay, ok, basically, actually, anyway, you know, I mean, I think, I guess, kind of, sort of
Trim the span start forward to a stronger opening word if needed (still respect {dmin:.0f}s minimum).

Reply with ONLY a JSON object (no prose, no code fences):
{{"shorts": [{{"t0": <float>, "t1": <float>, "cuts": [[<float>, <float>]], "rationale": "<short reason>", "title_suggestion": "<short title>", "opening_line": "<verbatim first ~8-12 words>", "hook_type": "question|provocation|claim", "hook_score": <0-10>, "context_score": <0-10>, "structure_score": <0-10>, "hook_payoff_coherence": <0-10>, "payoff_offset_sec": <float, 0..span_len>, "overall_score": <0-10>}}]}}""")
