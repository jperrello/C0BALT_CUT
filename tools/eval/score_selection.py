#!/usr/bin/env python3
# Tier-2 selection scorer (epic shorts-dwt / shorts-xoq). Deterministic, NO LLM.
# Scores a picker's spans (segments.raw.json) against a view-weighted gold set
# (goldset/<source>.json from build_goldset.py) on the pre-registered metrics:
#   recall@N, weighted-overlap (PRIMARY), rank-correlation, mean-IoU.
# Overlap convention (locked in PRE-REGISTRATION.md §2): coverage of a gold span =
#   intersection(gold, union-of-pick-cuts) / min(pick_dur, gold_dur); a gold span is
#   "covered" when that coverage >= tau (default 0.5).
#
#   score_selection.py score <goldset.json> <segments.raw.json> [--tau 0.5]
#   score_selection.py selftest
import argparse, json, sys
from scipy import stats


def pick_intervals(span):
    cuts = span.get("cuts") or [[span.get("t0", 0), span.get("t1", 0)]]
    return [(float(a), float(b)) for a, b in cuts if b > a]


def inter_union(gold, intervals):
    g0, g1 = gold
    return sum(max(0.0, min(g1, b) - max(g0, a)) for a, b in intervals)


def coverage(gold, span):
    g0, g1 = gold
    ints = pick_intervals(span)
    if not ints or g1 <= g0:
        return 0.0
    inter = inter_union((g0, g1), ints)
    pick_dur = sum(b - a for a, b in ints)
    denom = min(pick_dur, g1 - g0)
    return inter / denom if denom > 0 else 0.0


def score(goldset, picks, tau=0.5):
    gold = goldset.get("gold", [])
    if not gold:
        return {"error": "empty gold set", "n_gold": 0}
    total_views = sum(g.get("views", 0) for g in gold) or 1
    covered_views = 0.0
    covered_n = 0
    ious = []
    pairs = []  # (picker_overall_score, gold_views) for best-matched pick per gold
    for g in gold:
        gi = (float(g["t0"]), float(g["t1"]))
        best, best_cov = None, 0.0
        for p in picks:
            c = coverage(gi, p)
            if c > best_cov:
                best_cov, best = c, p
        ious.append(best_cov)
        if best_cov >= tau:
            covered_n += 1
            covered_views += g.get("views", 0)
            if best is not None and isinstance(best.get("overall_score"), (int, float)):
                pairs.append((float(best["overall_score"]), float(g.get("views", 0))))
    rc = float("nan")
    if len(pairs) >= 4:
        xs, ys = zip(*pairs)
        if len(set(xs)) > 1 and len(set(ys)) > 1:
            rc = float(stats.spearmanr(xs, ys).correlation)
    return {
        "n_gold": len(gold), "n_picks": len(picks), "tau": tau,
        "recall_at_n": covered_n / len(gold),
        "weighted_overlap": covered_views / total_views,   # PRIMARY metric
        "rank_corr": rc, "n_matched_pairs": len(pairs),
        "mean_iou": sum(ious) / len(ious),
    }


def selftest():
    # gold: two spans, a big-view winner [10,20] and a small one [100,110]
    goldset = {"gold": [{"t0": 10, "t1": 20, "views": 9000},
                        {"t0": 100, "t1": 110, "views": 1000}]}
    # picker lands squarely on the winner, misses the small one
    picks = [{"cuts": [[9, 21]], "overall_score": 8.0},
             {"cuts": [[200, 215]], "overall_score": 5.0}]
    r = score(goldset, picks, tau=0.5)
    fails = []
    if r["recall_at_n"] != 0.5:
        fails.append(f"recall_at_n {r['recall_at_n']} != 0.5")
    # weighted overlap credits the BIG winner: 9000/10000 = 0.9
    if abs(r["weighted_overlap"] - 0.9) > 1e-9:
        fails.append(f"weighted_overlap {r['weighted_overlap']} != 0.9")
    # coverage of winner: inter=10 (10..20), min(pickdur=12, golddur=10)=10 -> 1.0
    if abs(max(r["mean_iou"], 0) - 0.5) > 1e-9:  # (1.0 + 0.0)/2
        fails.append(f"mean_iou {r['mean_iou']} != 0.5")
    # partial-coverage threshold: a pick covering only 40% of a gold span must NOT count at tau=0.5
    g2 = {"gold": [{"t0": 0, "t1": 10, "views": 100}]}
    p2 = [{"cuts": [[0, 4]], "overall_score": 7}]  # covers 4s of 10s gold; min(4,10)=4 -> 1.0? no
    # coverage = inter(0..4)=4 / min(pickdur4, golddur10)=4 -> 1.0 (pick fully inside gold).
    # To test the tau gate we need a pick wider than gold catching only part:
    p3 = [{"cuts": [[5, 25]], "overall_score": 7}]  # inter=5 (5..10) / min(20,10)=10 -> 0.5
    if score(g2, p3, tau=0.6)["recall_at_n"] != 0.0:
        fails.append("tau gate failed: 0.5 coverage counted at tau=0.6")
    if score(g2, p3, tau=0.5)["recall_at_n"] != 1.0:
        fails.append("tau gate failed: 0.5 coverage not counted at tau=0.5")
    if fails:
        for f in fails:
            print("FAIL:", f, file=sys.stderr)
        return 1
    print("OK: recall@N, weighted-overlap (credits big winners), mean-IoU, tau gate all correct")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("score")
    sc.add_argument("goldset")
    sc.add_argument("segments")
    sc.add_argument("--tau", type=float, default=0.5)
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "selftest":
        return selftest()
    gs = json.load(open(a.goldset))
    picks = json.load(open(a.segments)).get("shorts", [])
    print(json.dumps(score(gs, picks, a.tau), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
