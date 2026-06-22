#!/usr/bin/env python3
# Build output/<slug>/_selection.json for ONE source from its work/<id>/ data:
#   (1) SHIPPED        — the produced shorts (scores + rationale from
#                        segments.raw.json), linked to their saved filename via
#                        clip_NN.done.completion.
#   (2) CONSIDERED     — the full candidates.hint.json RLM menu, each marked
#                        picked/unused by overlapping its [t0,t1] vs shipped cuts.
#   (3) TOPICS         — topics.json.
# Deterministic, no Claude, idempotent, non-fatal. Answers "show me the other
# arguments alongside the shorts" (shorts-aun).
import json, os, re, sys

work_dir = sys.argv[1].rstrip("/")
output_root = (sys.argv[2] if len(sys.argv) > 2 else "output").rstrip("/")

def load(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default

ingest = load(os.path.join(work_dir, "ingest.json"), {})
title = str(ingest.get("title") or ingest.get("id") or ingest.get("source_id") or "").strip()
slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or os.path.basename(work_dir)
dest_dir = os.path.join(output_root, slug)

raw = load(os.path.join(work_dir, "segments.raw.json"), {}).get("shorts", [])
hint = load(os.path.join(work_dir, "candidates.hint.json"), {}).get("candidates", [])
topics = load(os.path.join(work_dir, "topics.json"), {}).get("topics", [])

def shipped_name(i):
    p = os.path.join(work_dir, f"clip_{i + 1:02d}.done.completion")
    try:
        n = open(p).read().strip()
        return n or None
    except OSError:
        return None

SCORE_FIELDS = ("overall_score", "hook_score", "context_score", "structure_score",
                "hook_payoff_coherence", "payoff_offset_sec", "replay_quotient")

shipped = []
shipped_cuts = []   # (name, [[a,b],...]) for overlap marking
for i, s in enumerate(raw):
    cuts = s.get("cuts") or [[s.get("t0", 0), s.get("t1", 0)]]
    name = shipped_name(i)
    rec = {
        "rank": i + 1,
        "name": name,
        "delivered": bool(name) and os.path.isfile(os.path.join(dest_dir, name or "")),
        "t0": s.get("t0"), "t1": s.get("t1"), "cuts": cuts,
        "hook_type": s.get("hook_type"),
        "opening_line": s.get("opening_line", ""),
        "title_suggestion": s.get("title_suggestion", ""),
        "rationale": s.get("rationale", ""),
        "topic": s.get("topic", ""),
    }
    for f in SCORE_FIELDS:
        if f in s:
            rec[f] = s[f]
    if s.get("thread"):
        rec["thread"] = True
        rec["thread_kind"] = s.get("thread_kind", "")
    shipped.append(rec)
    shipped_cuts.append((name or f"rank{i + 1}", cuts))

def overlap(a0, a1, b0, b1):
    return max(0.0, min(a1, b1) - max(a0, b0))

considered = []
for c in hint:
    ct0, ct1 = float(c.get("t0", 0)), float(c.get("t1", 0))
    best_name, best_ov = None, 0.0
    for name, cuts in shipped_cuts:
        ov = sum(overlap(ct0, ct1, float(a), float(b)) for a, b in cuts)
        if ov > best_ov:
            best_ov, best_name = ov, name
    rec = {
        "t0": c.get("t0"), "t1": c.get("t1"),
        "quote": c.get("quote", ""), "why": c.get("why", ""),
        "confidence": c.get("confidence"),
        "picked": best_ov > 0.0,
        "picked_by": best_name if best_ov > 0.0 else None,
    }
    if c.get("thread"):
        rec["thread"] = True
        rec["kind"] = c.get("kind", "")
        rec["cuts"] = c.get("cuts", [])
        rec["bridge"] = c.get("bridge", "")
    considered.append(rec)

report = {
    "source_id": ingest.get("id") or os.path.basename(work_dir),
    "title": title,
    "url": ingest.get("url", ""),
    "slug": slug,
    "duration_sec": ingest.get("duration"),
    "shipped_count": len(shipped),
    "considered_count": len(considered),
    "considered_picked": sum(1 for c in considered if c["picked"]),
    "topics_count": len(topics),
    "shipped": shipped,
    "considered": considered,
    "topics": topics,
}

os.makedirs(dest_dir, exist_ok=True)
out = os.path.join(dest_dir, "_selection.json")
json.dump(report, open(out, "w"), indent=2)
print(out)
