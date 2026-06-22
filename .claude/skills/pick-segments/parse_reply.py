#!/usr/bin/env python3
# Parse Claude's reply, validate spans, write segments.json to stdout.
import json, re, sys

reply_path, n, dmin, dmax, transcript_path = sys.argv[1:6]
topics_path = sys.argv[6] if len(sys.argv) > 6 else ""
heatmap_path = sys.argv[7] if len(sys.argv) > 7 else ""
n, dmin, dmax = int(n), float(dmin), float(dmax)

# seconds the turn/payoff is allowed to take before we start penalizing.
PAYOFF_BUDGET = float(__import__("os").environ.get("PAYOFF_BUDGET_SEC", "3.0"))

heat = []
if heatmap_path:
    try:
        heat = json.load(open(heatmap_path)).get("heatmap", [])
    except (FileNotFoundError, ValueError):
        heat = []
heat_mean = (sum(float(p["value"]) for p in heat) / len(heat)) if heat else 0.0

def replay_quotient(cuts):
    # mean replay value across the span's cuts vs the source-wide mean.
    # 1.0 = average source moment; >1 = viewers rewatched this region.
    if not heat or heat_mean <= 0:
        return None
    tot = w = 0.0
    for a, b in cuts:
        for p in heat:
            o = min(b, float(p["end_time"])) - max(a, float(p["start_time"]))
            if o > 0:
                tot += float(p["value"]) * o
                w += o
    if w <= 0:
        return None
    return tot / w / heat_mean

topics = []
if topics_path:
    try:
        topics = json.load(open(topics_path)).get("topics", [])
    except FileNotFoundError:
        topics = []

def topic_of(t0, t1):
    for t in topics:
        if t0 >= t["t0"] - 0.25 and t1 <= t["t1"] + 0.25:
            return t
    return None

text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
if not m:
    print(f"pick-segments: no JSON in reply: {text!r}", file=sys.stderr)
    sys.exit(1)
data = json.loads(m.group(0))

tx = json.load(open(transcript_path))
duration = (tx.get("segments") or [{"t1": 0}])[-1]["t1"]

FILLERS = {"so","and","but","um","uh","like","well","okay","ok","basically","actually","anyway"}
FILLER_BIGRAMS = {("you","know"),("i","mean"),("i","think"),("i","guess"),("kind","of"),("sort","of")}
# High-precision sentence-fragment openers: words that almost never begin a
# clean, self-contained hook (a scrolling stranger hears a mid-clause scrap,
# e.g. "of picturing what's happened..."). Conservative on purpose — temporal
# openers ("in/after/before/when") CAN hook a cold viewer, so they're excluded.
FRAGMENT_OPENERS = {"of","than","nor","whom","whose","thereof","therein","wherein","whereby","whereas"}

def first_words(t0, k=2):
    words = tx.get("words") or []
    if not words:
        for seg in tx.get("segments") or []:
            if seg["t1"] >= t0:
                return [w.strip(".,?!").lower() for w in seg["text"].split()[:k]]
        return []
    out = []
    for w in words:
        if w.get("t0", 0) + 0.05 >= t0:
            out.append(w["w"].strip(".,?!").lower())
            if len(out) >= k:
                break
    return out

def starts_with_filler(t0):
    fw = first_words(t0, 2)
    if not fw:
        return False
    if fw[0] in FILLERS or fw[0] in FRAGMENT_OPENERS:
        return True
    if len(fw) >= 2 and (fw[0], fw[1]) in FILLER_BIGRAMS:
        return True
    return False

shorts = []
seen = []
def norm_cuts(sh):
    # validate/normalize the cuts list: in-bounds, ordered, non-overlapping.
    # falls back to a single [t0,t1] cut when cuts are missing/unusable.
    raw = sh.get("cuts")
    cuts = []
    if isinstance(raw, list):
        for c in raw:
            try:
                a, b = float(c[0]), float(c[1])
            except (TypeError, ValueError, IndexError):
                continue
            if b - a < 0.5:
                continue
            if duration and (a < 0 or b > duration + 1):
                continue
            cuts.append([a, b])
    if not cuts:
        cuts = [[float(sh["t0"]), float(sh["t1"])]]
    cuts.sort(key=lambda c: c[0])
    merged = [cuts[0]]
    for a, b in cuts[1:]:
        if a >= merged[-1][1]:        # drop overlapping cuts, keep chronological
            merged.append([a, b])
    return [[round(a, 2), round(b, 2)] for a, b in merged]


# Open-loop hooks (a question/provocation opens a curiosity gap a stranger needs
# filled) out-rank a flat claim at equal sub-scores — up to a few rank points.
OPENLOOP = {"question": 4.0, "provocation": 3.0, "claim": 0.0}


def score99(item):
    # Explicit 0-99 upload-readiness rank, recomputed deterministically from the
    # sub-scores so the formula — not Claude's holistic guess — drives selection.
    #
    # base 0-85: weighted blend of the four 0-10 sub-scores. structure (the
    # complete arc) and hook<->payoff coherence (the hook actually lands, vs bait)
    # weigh heaviest, then cold-open hook, then standalone context.
    #   structure 2.6 + coherence 2.6 + hook 1.8 + context 1.5 = 8.5 -> *10 = 85 max
    base = (item["structure_score"] * 2.6
            + item["hook_payoff_coherence"] * 2.6
            + item["hook_score"] * 1.8
            + item["context_score"] * 1.5)
    # time-to-first-payoff penalty: subtract proportional to how far past the
    # budget the turn lands. ~2.2 rank pts per second late, capped so a single
    # term can't sink an otherwise strong arc below the floor.
    penalty = min(20.0, max(0.0, item["payoff_offset_sec"] - PAYOFF_BUDGET) * 2.2)
    # open-loop bonus: question/provocation hooks create the curiosity gap that
    # stops a scroll; reward them over a flat claim.
    openloop = OPENLOOP.get(item["hook_type"], 0.0)
    s = base - penalty + openloop
    return max(0.0, min(99.0, s))


def nudge_t0(cuts, offset):
    # When the payoff lands well past the budget and the pre-turn material is
    # pure setup, nudge the FIRST cut's start forward toward the turn line so the
    # delivered open lands closer to the payoff. Conservative: never crosses the
    # turn, never trims more than the overshoot, never drops total cut duration
    # below dmin, and only fires on single-window leads (multi-cut spans already
    # assemble a deliberate Q->A and must not be re-cut here).
    if offset <= PAYOFF_BUDGET + 1.0:
        return cuts, 0.0
    a0, b0 = cuts[0]
    total = sum(b - a for a, b in cuts)
    room = total - dmin                 # how much we may shave and stay >= dmin
    if room <= 0.5:
        return cuts, 0.0
    # leave PAYOFF_BUDGET of runway before the turn; never past the turn itself.
    shift = min(offset - PAYOFF_BUDGET, room, (b0 - a0) - 0.5)
    if shift <= 0.5:
        return cuts, 0.0
    out = [[round(a0 + shift, 2), b0]] + [list(c) for c in cuts[1:]]
    return out, round(shift, 2)


for sh in data.get("shorts", []):
    try:
        cuts = norm_cuts(sh)
    except (KeyError, TypeError, ValueError):
        continue
    t0 = cuts[0][0]
    t1 = cuts[-1][1]
    if t1 <= t0:
        continue
    if duration and (t0 < 0 or t1 > duration + 1):
        continue
    dur = sum(b - a for a, b in cuts)   # final runtime = sum of cut lengths
    if dur < dmin - 0.5 or dur > dmax + 0.5:
        continue
    if any(not (t1 <= a or t0 >= b) for a, b in seen):
        continue
    # A cross-chunk THREAD span (shorts-8la) is the sanctioned exception to the
    # single-topic rule: a deliberate setup->payoff/callback/contradiction stitch
    # of >=2 non-contiguous cuts. It bypasses the topic-boundary drop here and —
    # being multi-cut — already bypasses verify-coherence tightening downstream.
    is_thread = bool(sh.get("thread")) and len(cuts) >= 2
    tp = topic_of(t0, t1) if topics else None
    if topics and tp is None and not is_thread:
        print(f"pick-segments: dropping span {t0:.1f}-{t1:.1f} (crosses topic boundary)", file=sys.stderr)
        continue
    if starts_with_filler(t0):
        print(f"pick-segments: dropping span {t0:.1f}-{t1:.1f} (filler/fragment opening)", file=sys.stderr)
        continue
    seen.append((t0, t1))
    span_len = sum(b - a for a, b in cuts)
    offset = float(sh.get("payoff_offset_sec", 0) or 0)
    offset = max(0.0, min(span_len, offset))   # clamp into the delivered window
    # bias the open toward the turn line when the lead is pure setup — but never
    # re-cut a deliberate thread stitch (its cuts are intentional).
    cuts, shift = ([list(c) for c in cuts], 0.0) if is_thread else nudge_t0(cuts, offset)
    if shift > 0:
        t0 = cuts[0][0]
        t1 = cuts[-1][1]
        offset = max(0.0, offset - shift)      # turn is now that much closer to the open
    item = {
        "t0": round(t0, 2),
        "t1": round(t1, 2),
        "cuts": cuts,
        "rationale": sh.get("rationale", "")[:280],
        "title_suggestion": sh.get("title_suggestion", "")[:120],
        "opening_line": str(sh.get("opening_line", "")).strip()[:160],
        "hook_type": (str(sh.get("hook_type", "")).strip().lower()
                      if str(sh.get("hook_type", "")).strip().lower()
                      in ("question", "provocation", "claim") else "claim"),
        "hook_score": float(sh.get("hook_score", 0) or 0),
        "context_score": float(sh.get("context_score", 0) or 0),
        "structure_score": float(sh.get("structure_score", 0) or 0),
        # NEW sub-scores surfaced for the grader/verifier downstream.
        "hook_payoff_coherence": float(sh.get("hook_payoff_coherence", 0) or 0),
        "payoff_offset_sec": round(offset, 2),
    }
    if tp is not None:
        item["topic"] = tp.get("title", "")
    if is_thread:
        item["thread"] = True
        k = str(sh.get("thread_kind", "") or sh.get("kind", "")).strip().lower()
        item["thread_kind"] = k if k in ("setup_payoff", "callback", "escalation", "contradiction") else "setup_payoff"
        item.setdefault("topic", f"thread:{item['thread_kind']}")
    # explicit 0-99 rank from the sub-scores (replaces the old 0-10 passthrough).
    item["overall_score"] = round(score99(item), 2)
    rq = replay_quotient(cuts)
    if rq is not None:
        # Replay is a weak tie-breaker. It often marks the memorable sentence
        # inside a larger explanation, so it must not overpower the arc judgment.
        # Rescaled to the 0-99 range (+0.4 -> +4.0) so it stays proportional.
        item["replay_quotient"] = round(rq, 2)
        item["overall_score"] = round(
            min(99.0, item["overall_score"] + min(4.0, max(0.0, (rq - 1.0) * 4.0))), 2)
    shorts.append(item)

def rank_key(s):
    # Tie-breaker layered on the 0-99 overall_score. The open-loop up-weight and
    # the time-to-payoff penalty already live INSIDE overall_score (score99), so
    # this only adds a small residual hook-strength nudge — scaled to the 0-99
    # range (~x10 the old 0-10 weights) so it stays a near-gate, not a re-rank.
    bonus = max(-8.0, min(3.0, (s.get("hook_score", 0.0) - 6.0) * 1.5))
    return s["overall_score"] + bonus

shorts.sort(key=lambda s: -rank_key(s))
shorts = shorts[:n]
shorts.sort(key=lambda s: s["t0"])
json.dump({"source": tx.get("source", ""), "shorts": shorts}, sys.stdout, indent=2)
