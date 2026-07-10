#!/usr/bin/env python3
# Build a compact prompt for Claude: transcript lines + RMS profile.
import json, os, sys

# ADVICE_CORPUS toggle (epic shorts-dwt / shorts-874). OFF (default) = today's prompt
# byte-for-byte; ON prepends the versioned §9 entertainment-advice corpus and nothing else,
# so any ON-vs-OFF selection difference is attributable to the corpus alone.
advice_block = ""
if os.environ.get("ADVICE_CORPUS", "0") == "1":
    try:
        corpus = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "advice.md")).read().strip()
        advice_block = corpus + "\n\n---\n\n"
    except OSError:
        advice_block = ""

transcript_path, rms_path, n, dmin, dmax = sys.argv[1:6]
topics_path = sys.argv[6] if len(sys.argv) > 6 else ""
heatmap_path = sys.argv[7] if len(sys.argv) > 7 else ""
hint_path = sys.argv[8] if len(sys.argv) > 8 else ""
thesis_path = sys.argv[9] if len(sys.argv) > 9 else ""
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
# back-half arcs the compressed transcript view can miss. HINT only. Candidates
# carry a confidence (0-1) so they're surfaced RANKED, not flat (shorts-7mk), and
# may be cross-chunk THREAD stitches with their own cut plan (shorts-qw3/8la).
hint_block = ""
if hint_path:
    try:
        cands = json.load(open(hint_path)).get("candidates", [])
    except (FileNotFoundError, ValueError):
        cands = []
    simple = [c for c in cands if not c.get("thread")]
    threads = [c for c in cands if c.get("thread")]
    # already confidence-ranked upstream; keep that order, show the score.
    if simple:
        rows = "\n".join(
            f"  [conf {float(c.get('confidence', 0.5)):.2f}] [{c['t0']:.1f}-{c['t1']:.1f}] "
            f"{str(c.get('quote','')).strip()[:160]}"
            for c in simple
        )
        hint_block += f"""
CANDIDATE MOMENTS (rlm discovery hint — clip-worthy beats surfaced from a full-resolution per-chunk read; especially useful for the back half of long videos; RANKED by confidence = how standalone the moment looked):
{rows}

Treat these as DISCOVERY HINTS, but weight confidence heavily: it is a second reader's estimate, from the full-resolution transcript, of how strong each moment is as a standalone short. Higher confidence = a stronger lead.

NEAR-MANDATORY: every candidate at confidence >= 0.85 is among the strongest standalone moments in the entire source — the discovery pass is telling you these are the bangers. Build a complete setup → turn → landing arc around EACH of them (expand the bare quote; use QUESTION-LEAD ASSEMBLY when its natural open is slow) and INCLUDE all of them among your {n} picks. Drop a >= 0.85 candidate only if a genuinely STRONGER moment in the same topic crowds it out, or it truly cannot stand alone for a cold viewer — never merely because a different topic caught your eye first. A high-confidence candidate you silently skip is a missed clip, not a judgment call. (A deterministic backfill will re-inject any >= 0.85 candidate you omit, so it is better to assemble a proper arc here than to leave it to the fallback.)

Never pick a bare quote because it appears here — always expand it to a full arc.
"""
    if threads:
        trows = "\n".join(
            "  [conf {:.2f}] [{}] cuts {} :: {}\n      bridge: {}".format(
                float(c.get('confidence', 0.6)),
                str(c.get('kind', 'setup_payoff')),
                " + ".join(f"[{float(r[0]):.1f}-{float(r[1]):.1f}]"
                           for r in (c.get('cuts') or [])
                           if isinstance(r, (list, tuple)) and len(r) >= 2),
                str(c.get('quote', '')).strip()[:140],
                str(c.get('bridge', '')).strip()[:200],
            )
            for c in threads
        )
        hint_block += f"""
CROSS-CHUNK THREADS (rlm discovery hint — a setup in one part of the video that pays off in a DISTANT part: setup→payoff, callback, escalation, or contradiction, stitched with non-contiguous cuts):
{trows}

A thread is the ONE case where a short MAY cross topic boundaries. If a thread above is genuinely compelling as a standalone story, you may pick it: provide its ordered cuts (≤3, source-chronological, summing to {dmin:.0f}-{dmax:.0f}s), set "thread": true, AND set "thread_kind" to that thread's kind (setup_payoff | callback | escalation | contradiction) so it bypasses the single-topic constraint. Only do this for a REAL narrative stitch the cuts make coherent — never to glue two loosely-related moments. Most picks are still single-topic; treat threads as rare, high-value exceptions.
"""

# source subject/spine (from derive-thesis) — the theme prior. A 2h talk is
# mostly ON-SPINE material plus entertaining tangents; without this the picker
# maximizes standalone virality and ships clip-shaped asides that misrepresent
# the source (shorts-ix43). Absent => no block, picker runs theme-blind as before.
theme_block = ""
if thesis_path:
    try:
        thesis = json.load(open(thesis_path))
    except (FileNotFoundError, ValueError):
        thesis = {}
    subject = str(thesis.get("subject", "")).strip()
    if subject:
        sentence = (f"\n  throughline: {str(thesis['thesis_sentence']).strip()}"
                    if str(thesis.get("thesis_sentence", "")).strip() else "")
        threads = [str(x).strip() for x in (thesis.get("key_threads") or []) if str(x).strip()]
        tline = ("\n  on-spine sub-themes: " + "; ".join(threads)) if threads else ""
        theme_block = f"""
SOURCE SUBJECT — the SPINE of the whole video (highest-level selection prior):
  subject: {subject}{sentence}{tline}

This source wanders through many chapters, but most viewers came for its SPINE. A short that ADVANCES or ILLUSTRATES the subject above represents the episode; an entertaining but OFF-SPINE tangent (a random anecdote with nothing to do with the subject) makes a clip-shaped short that misrepresents the source — this is the exact failure we are fixing. STRONGLY PREFER on-spine moments. An off-spine tangent must be a genuinely irresistible standalone story to earn a pick over an on-spine moment, and never fill more than ONE of your {n} picks. Score each pick's theme_fit honestly (below); the deterministic ranker down-weights off-spine picks.
"""

# The atomic unit of a short is ONE IDEA, not one chapter (shorts-sgpa). Topics
# are a MAP of where ideas live, not a fence. A single continuous cut stays in
# one topic; a multi-cut short may assemble the same idea from cuts in DIFFERENT
# topics. ASSEMBLE_CROSS_TOPIC=0 restores the old single-topic hard constraint.
CROSS_TOPIC = os.environ.get("ASSEMBLE_CROSS_TOPIC", "1") != "0"
if topics:
    topic_block = "\n".join(
        f"  topic {i+1} [{t['t0']:.1f}-{t['t1']:.1f}] {t.get('title','')}: {t.get('summary','')}"
        for i, t in enumerate(topics)
    )
    if CROSS_TOPIC:
        topic_rules = f"""
TOPIC MAP (where the ideas live in this source — a guide, NOT a fence):
{topic_block}

The atomic unit of a short is ONE IDEA, not one chapter. These chapters just show where each idea sits. Two rules govern how cuts relate to them:
  - A SINGLE continuous cut must stay inside one topic (a raw slice that runs across a chapter change is two half-ideas, not one clean idea).
  - A MULTI-CUT short MAY pull its cuts from DIFFERENT topics — but ONLY when every cut develops the SAME single idea (a point set up in one chapter and paid off in another; a claim here and its vivid example far later; a question and its answer). This is the whole point: the same idea revisited across the video becomes one tight short.
The ONLY thing forbidden is gluing two DIFFERENT ideas together. If a topic is shorter than {dmin:.0f}s, don't force a lone single-cut pick from it. You don't need to pick from every topic; pick the {n} strongest IDEAS overall, wherever their pieces live.
"""
    else:
        topic_rules = f"""
TOPIC BOUNDARIES (HARD CONSTRAINT):
{topic_block}

Each picked span MUST lie entirely within ONE topic — never straddle a boundary. A short that crosses topics reads as two unrelated clips spliced together; that is the failure mode we are explicitly preventing. If a topic is shorter than {dmin:.0f}s, skip it. You do not need to pick from every topic; pick the {n} strongest single-topic moments overall. (The ONE exception is a deliberate cross-chunk THREAD from the threads hint below, marked "thread": true — see that block.)
"""
else:
    topic_rules = ""

print(f"""{advice_block}You are picking clip-worthy spans for vertical shorts.

Source duration: {duration:.1f}s
Audio energy (per ~1s of source, bucketed to ~60 bins, ▁ low → █ high):
{spark}
{replay_block}
Transcript (timestamped lines, seconds):
{transcript_block}
{theme_block}{topic_rules}{hint_block}
Pick {n} non-overlapping shorts, each {dmin:.0f}-{dmax:.0f} seconds of SOURCE story selected, that would work as standalone shorts. Avoid mid-sentence cuts.

SELECTION BUDGET vs DELIVERED LENGTH (read this): the {dmin:.0f}-{dmax:.0f}s window is how much SOURCE story you select — NOT the final runtime. After you pick, downstream editing (filler removal + pace tightening) shaves roughly 20-30% of the dead air and trail-offs. So select the FULLER arc — include the complete setup and the landing — and trust the editor to tighten it into the ~30-40s sweet spot. Do NOT pre-trim the arc to hit a short target; an arc that already feels minimal at selection will land truncated after tightening.

STANDALONE CONTEXT (hard priority):
A good pick must make sense to a cold viewer with no surrounding podcast context. It needs:
  - setup: enough premise for the viewer to know what question/problem/example is being discussed.
  - turn: the surprising claim, conflict, demonstration, or insight.
  - landing: the speaker's explanation of why the turn matters, not just the last shocking phrase.

Reject a span if it is merely a highlight, definition, example, punchline, or replay spike without the surrounding thought. It is better to choose a less flashy topic with a complete arc than a hotter moment that ends abruptly. For long-form explainers and interviews, prefer 40-55 seconds of source when that is what the idea needs; use the minimum length only when the whole idea truly lands in less.

ASSEMBLE THE STORY WITH CUTS (this is the core craft): a great short is EDITED like a conversation, not sliced raw. Each short is built from 1-3 source segments ("cuts") joined end-to-end into ONE flowing idea. Most strong moments are a single continuous cut — use that when the whole idea lives in one clean stretch. But the same idea is often developed in PIECES scattered across the video: set up at 6:00, sharpened at 9:00, paid off at 13:00, with dead air and other topics in between. When that makes the better short, ASSEMBLE it — take the 2-3 best pieces of that ONE idea from WHEREVER they live in the source, drop everything between, and deliver one tight, self-contained conversation. Think like an editor cutting a guest's best articulation of a single point together, not a knife making one slice.
  - Provide "cuts": a list of [start, end] source-second ranges, in SOURCE-CHRONOLOGICAL order, non-overlapping. The cuts play back-to-back.
  - Every cut in a short must develop the SAME ONE idea. Cuts MAY come from different topics/chapters when they are that same idea (setup→payoff, claim→example, question→answer, callback). The ONLY hard rule: never glue two DIFFERENT ideas together.
  - Name that idea in the "idea" field (ONE sentence): the single throughline all your cuts share. If you can't state it in one sentence, the cuts are not one idea — don't stitch them.
  - The SUM of cut durations must be {dmin:.0f}-{dmax:.0f}s. Keep cuts to 1-3; don't over-chop.
  - t0 = first cut's start, t1 = last cut's end.
  - A single-cut short is just "cuts": [[t0, t1]] — fine and common.
  - QUESTION-LEAD ASSEMBLY: a cold viewer stops for a hook they instantly get (see COLD-OPEN HOOK below). If the best idea's payoff is strong but its natural opening is slow, make your FIRST cut a short question or provocation pulled from EARLIER in the source that sets up exactly this payoff, then cut straight to the payoff. The lead-in must be about the SAME idea — you are restoring the Q→A the edit lost, never bolting on an unrelated question — and must occur earlier in the source than the payoff (cuts always play in source-chronological order).

COLD-OPEN HOOK (THE single most important thing — a short that doesn't grab in the FIRST SECOND is dead):
There is NO title card and NO on-screen text explaining this clip — the SCRIPT alone carries the hook. The FIRST SPOKEN SENTENCE by itself must make a scrolling stranger stop in about ONE second (assume they hear it muted, then unmute). No preamble, no throat-clearing. The strongest openings are understandable with ZERO context:
  - a QUESTION a stranger has also wondered ("How come I can see the moon during the day?", "What's more likely, teleportation or time travel?"),
  - a PROVOCATION / contrarian claim ("the richest women in the world — almost all of it is divorce money"),
  - or a striking, concrete factual claim with a named subject or a number.
PREFER spans whose literal first spoken sentence is already one of these; use QUESTION-LEAD ASSEMBLY (above) to pull a hook to the front when the best idea's natural open is weak. A pick whose spoken opening does NOT stop a stranger in ~1s should not be chosen at all — there is no title to rescue it. Score each pick on:
  - hook_score (0-10): does the FIRST SPOKEN SECOND land one of the three openings above for a cold viewer with no title and no context? Reward direct questions, contrarian provocations, concrete nouns, numbers, named subjects. Punish vague setup, pronouns with no referent, and slow throat-clearing HARD — a weak spoken opener is fatal now.
  - context_score (0-10): can a cold viewer understand the setup, the turn, and why the ending matters without the surrounding sentences? Penalize abrupt endings hard.
  - structure_score (0-10): does the span have hook → foreshadow → payoff → landing, with but/therefore causality between beats (not just "and then")? Does it open a curiosity loop that resolves by the end?
  - hook_payoff_coherence (0-10): does the cold-open hook ACTUALLY pay off inside this span? A 10 means the opening question/provocation/claim is directly answered, resolved, or delivered on by the turn and landing. Score LOW when the open is bait that never lands — a juicy first line whose promise the rest of the span never honors, or a turn about something other than what the hook set up. This is the anti-clickbait term: reward openings whose curiosity loop closes; punish bait-and-switch.
  - payoff_offset_sec (0..span_len): seconds from the DELIVERED span start to the exact line where the turn/insight/payoff lands (the moment the curiosity loop starts resolving). 0 means the very first sentence is already the turn. THE TURN MUST LAND WITHIN ~2s OF THE DELIVERED OPEN — a payoff that lands 10s in is a setup-heavy bait-opener that loses the cold viewer before the reward. If the natural payoff is late but strong, use QUESTION-LEAD ASSEMBLY (above) to pull a short setup-question cut to the front so payoff_offset_sec stays small. Measure honestly against the cuts you chose: it is the offset within the assembled, delivered short, not the raw source.
  - theme_fit (0-10): does THIS moment advance or illustrate the SOURCE SUBJECT above? 10 = squarely on the spine (a core-theme insight or its best illustration); 5 = tangentially related; 0 = an entertaining but off-spine tangent with nothing to do with the subject. If NO SOURCE SUBJECT was given above, score 5 for every pick.
  - ending_open_loop (0-10): judge the LAST DELIVERED SENTENCE. 8-10 = it leaves a debatable open question, an unresolved "that being said..." thread, or theory-bait viewers will argue about in comments (drives rewatch + loop); 4-7 = a satisfying landing that still invites reflection; 0-3 = a closed flat statement or bare statistic that ends the conversation dead. The arc must still COMPLETE (structure_score is unaffected) — this rewards an ending that resolves the promised payoff yet leaves one thread open.
  - overall_score (0-10): your holistic rank — would you stop scrolling AND watch to the end? Weigh complete standalone meaning first, then cold-open hook strength (PREFER open-loop question/provocation hooks over flat claims), then how fast the payoff lands, then vocal energy/affect, concrete stakes, RMS peaks, and replay peaks. RMS/replay can break ties but cannot rescue a confusing, abrupt, or slow-to-pay-off clip. (Note: the deterministic ranker recomputes the final 0-99 rank from your sub-scores — including hook_payoff_coherence and payoff_offset_sec — so rate every field honestly rather than gaming overall_score.)
Also report, for each pick:
  - opening_line: the verbatim first ~8-12 words a viewer hears (after any question-lead assembly).
  - hook_type: "question", "provocation", or "claim" — what that opening line is. PREFER open-loop "question" and "provocation" hooks (they create a curiosity gap a stranger needs filled) over flat "claim" hooks.

HARD REJECT — do NOT pick spans whose first transcript word is filler:
  so, and, but, um, uh, like, well, okay, ok, basically, actually, anyway, you know, I mean, I think, I guess, kind of, sort of
Trim the span start forward to a stronger opening word if needed (still respect {dmin:.0f}s minimum).

Reply with ONLY a JSON object (no prose, no code fences):
{{"shorts": [{{"t0": <float>, "t1": <float>, "cuts": [[<float>, <float>]], "idea": "<ONE sentence: the single throughline all cuts share>", "thread_kind": "<optional: setup_payoff|callback|escalation|contradiction — label the assembly type when a multi-cut short spans different topics>", "rationale": "<short reason>", "title_suggestion": "<short title>", "opening_line": "<verbatim first ~8-12 words>", "hook_type": "question|provocation|claim", "hook_score": <0-10>, "context_score": <0-10>, "structure_score": <0-10>, "hook_payoff_coherence": <0-10>, "payoff_offset_sec": <float, 0..span_len>, "theme_fit": <0-10>, "ending_open_loop": <0-10>, "overall_score": <0-10>}}]}}""")
