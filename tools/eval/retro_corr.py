#!/usr/bin/env python3
# T3 retrospective correlation (epic shorts-dwt / shorts-6io).
# Join: analytics CSV (title -> views/CTR/watch-time)
#         -> output/<slug>/<name>.mp4
#         -> work/<id>/clip_NN.done.completion  (delivered file <-> span)
#         -> segments.raw.json span (picker sub-scores)
# Extract existing picker scores + NEW falsifiable advice features (all deterministic,
# NO Claude) and rank-correlate each against a real audience outcome with bootstrap CIs
# + Benjamini-Hochberg FDR. Reports which §9 advice claims hold / fail / reverse on
# THIS channel's own audience. Observational, small-n: prunes claims, never confirms.
#
# usage: python3 tools/eval/retro_corr.py [--csv PATH] [--work work] [--output output]
#                                         [--out tools/eval/retro_report] [--boot 10000]
import argparse, csv, glob, json, math, os, re, sys
import numpy as np
from scipy import stats

FRAGMENT_OPENERS = {"of", "than", "nor", "whom", "whose", "thereof", "therein",
                    "wherein", "whereby", "whereas"}
HEDGES = ["it depends", "to be fair", "i think", "i guess", "i mean", "you know",
          "kind of", "sort of", "i suppose", "probably", "maybe", "perhaps",
          "i'm not sure", "i would say", "in a sense", "more or less"]
PIVOTS = {"but", "however", "yet", "actually", "although", "though", "except",
          "until", "suddenly", "turns"}  # "turns out"
QUESTION_OPENERS = {"what", "why", "how", "who", "when", "where", "is", "are",
                    "do", "does", "did", "can", "could", "would", "should", "have"}
NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight",
                "nine", "ten", "hundred", "thousand", "million", "billion",
                "first", "second", "third", "percent", "half", "double"}
# High-arousal emotion lexicon (anger / awe / anxiety / humor) — heuristic, NOT a Claude call.
AROUSAL = {
    "anger": {"hate", "furious", "angry", "rage", "pissed", "insane", "crazy", "ridiculous",
              "stupid", "wrong", "lie", "lying", "fight", "destroy", "kill", "war", "attack"},
    "awe": {"incredible", "amazing", "insane", "unbelievable", "mind", "blown", "universe",
            "infinite", "impossible", "extraordinary", "stunning", "wow", "god", "cosmic",
            "massive", "enormous", "greatest", "never", "ever", "history"},
    "anxiety": {"scared", "afraid", "fear", "terrified", "danger", "dangerous", "death",
                "die", "dying", "risk", "threat", "panic", "worried", "nervous", "dark"},
    "humor": {"funny", "hilarious", "laugh", "joke", "lol", "haha", "ridiculous", "wild",
              "crazy", "dude", "bro", "literally", "absolutely"},
}
JARGON_RE = re.compile(r"^[a-z]{13,}$")  # crude long-word proxy for technical jargon

# The §9 advice claims, made falsifiable: feature -> sign the corpus PREDICTS for retention.
# +1 = corpus says this raises retention; -1 = corpus says it lowers it.
ADVICE_CLAIM = {
    "opening_hedge": -1, "fragment_opener": -1, "jargon_density": -1,
    "has_pivot": +1, "opens_question": +1, "opens_number": +1,
    "arousal_density": +1, "arousal_awe": +1, "arousal_anxiety": +1, "arousal_humor": +1,
}


def norm_tokens(s):
    return [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t]


def kebab(s):
    return re.sub(r"[^a-z0-9]+", "-", s.split("#")[0].lower()).strip("-")


def jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if (a or b) else 0.0


def load_csv(path):
    out = {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            vid = (r.get("Content") or "").strip()
            title = (r.get("Video title") or "").strip()
            if not title or vid.lower() == "total":
                continue
            views = float(re.sub(r"[^0-9.]", "", r.get("Views") or "0") or 0)
            watch = float(re.sub(r"[^0-9.]", "", r.get("Watch time (hours)") or "0") or 0)
            ctr = float(re.sub(r"[^0-9.]", "", r.get("Impressions click-through rate (%)") or "0") or 0)
            dur = float(re.sub(r"[^0-9.]", "", r.get("Duration") or "0") or 0)
            if views <= 0:
                continue
            avd = watch * 3600.0 / views  # average view duration, seconds
            out[kebab(title)] = {
                "video_id": vid, "title": title, "views": views, "watch_hours": watch,
                "ctr": ctr, "duration": dur, "avd_sec": avd,
                "avd_frac": (avd / dur if dur > 0 else float("nan")),
                "title_tokens": norm_tokens(title.split("#")[0]),
            }
    return out


def index_delivered(work_root, output_root):
    # delivered filename -> {work_id, span, clip_transcript}
    idx = {}
    for seg_path in glob.glob(os.path.join(work_root, "*", "segments.raw.json")):
        wd = os.path.dirname(seg_path)
        try:
            shorts = json.load(open(seg_path)).get("shorts", [])
        except Exception:
            continue
        for i, span in enumerate(shorts):
            comp = os.path.join(wd, f"clip_{i + 1:02d}.done.completion")
            try:
                name = open(comp).read().strip()
            except OSError:
                continue
            if not name:
                continue
            # opening text source: the rebased/assembled clip-local transcript (real t0)
            ctx = None
            for cand in (f"clip_{i + 1:02d}.transcript.json",
                         f"clip_{i + 1:02d}.trim.transcript.json",
                         f"clip_{i + 1:02d}.tight.transcript.json"):
                p = os.path.join(wd, cand)
                if os.path.isfile(p):
                    ctx = p
                    break
            idx[os.path.splitext(name)[0]] = {
                "work_id": os.path.basename(wd), "span": span, "name": name,
                "ctx": ctx,
            }
    return idx


def clip_words(ctx):
    if not ctx:
        return []
    try:
        return [w.get("w", "") for w in json.load(open(ctx)).get("words", [])]
    except Exception:
        return []


def features(span, words):
    toks = [t for w in words for t in norm_tokens(w)]
    n = len(toks) or 1
    opening = toks[:25]  # first ~25 words ≈ opening sentence(s)
    op_text = " ".join(opening)
    f = {}
    # existing picker sub-scores (defensive — fields vary across runs)
    for k in ("hook_score", "context_score", "structure_score", "hook_payoff_coherence",
              "payoff_offset_sec", "overall_score", "replay_quotient"):
        v = span.get(k)
        if isinstance(v, (int, float)):
            f[k] = float(v)
    ht = (span.get("hook_type") or "").lower()
    if ht:
        f["hook_is_question"] = 1.0 if ht == "question" else 0.0
        f["hook_is_provocation"] = 1.0 if ht == "provocation" else 0.0
    # NEW falsifiable advice features (the §9 claims, made measurable)
    f["opening_hedge"] = 1.0 if any(h in op_text for h in HEDGES) else 0.0
    f["has_pivot"] = 1.0 if (set(toks) & PIVOTS) else 0.0
    f["fragment_opener"] = 1.0 if (opening and opening[0] in FRAGMENT_OPENERS) else 0.0
    f["jargon_density"] = sum(1 for t in toks if JARGON_RE.match(t)) / n
    f["opens_question"] = 1.0 if (opening and opening[0] in QUESTION_OPENERS) else 0.0
    f["opens_number"] = 1.0 if any(t.isdigit() or t in NUMBER_WORDS for t in opening) else 0.0
    arousal_hits = sum(1 for t in toks if any(t in lex for lex in AROUSAL.values()))
    f["arousal_density"] = arousal_hits / n
    for cls, lex in AROUSAL.items():
        f[f"arousal_{cls}"] = sum(1 for t in opening if t in lex) / (len(opening) or 1)
    f["_n_words"] = float(n)
    return f


def spearman_boot(x, y, B, seed):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    n = len(x)
    if n < 4 or np.std(x) == 0 or np.std(y) == 0:
        return {"rho": float("nan"), "p": float("nan"), "ci": [float("nan")] * 2,
                "n": int(n), "frac_pos": float("nan")}
    rho, p = stats.spearmanr(x, y)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(B):
        idx = rng.integers(0, n, n)
        bx, by = x[idx], y[idx]
        if np.std(bx) == 0 or np.std(by) == 0:
            continue
        boots.append(stats.spearmanr(bx, by).correlation)
    boots = np.array([b for b in boots if np.isfinite(b)])
    lo, hi = np.percentile(boots, [2.5, 97.5]) if len(boots) else (float("nan"),) * 2
    return {"rho": float(rho), "p": float(p), "ci": [float(lo), float(hi)],
            "n": int(n), "frac_pos": float(np.mean(boots > 0)) if len(boots) else float("nan")}


def bh_fdr(pvals, q=0.10):
    # Benjamini-Hochberg: returns set of indices that pass at FDR q
    items = sorted((p, i) for i, p in enumerate(pvals) if np.isfinite(p))
    m = len(items)
    passed = set()
    thresh = 0
    for rank, (p, i) in enumerate(items, 1):
        if p <= (rank / m) * q:
            thresh = rank
    for rank, (p, i) in enumerate(items, 1):
        if rank <= thresh:
            passed.add(i)
    return passed


def main():
    ap = argparse.ArgumentParser()
    default_csv = sorted(glob.glob(os.path.expanduser(
        "~/Downloads/*C0BALT*/Table data.csv")), key=os.path.getmtime)
    ap.add_argument("--csv", default=default_csv[-1] if default_csv else None)
    ap.add_argument("--work", default="work")
    ap.add_argument("--output", default="output")
    ap.add_argument("--out", default="tools/eval/retro_report")
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--jaccard", type=float, default=0.6)
    ap.add_argument("--seed", type=int, default=1729)
    a = ap.parse_args()
    if not a.csv or not os.path.isfile(a.csv):
        print("no analytics CSV found", file=sys.stderr)
        sys.exit(1)

    csvrows = load_csv(a.csv)
    delivered = index_delivered(a.work, a.output)
    stems = list(delivered)

    matched = []
    unmatched = []
    for slug, row in csvrows.items():
        name, conf, how = None, 0.0, None
        if slug in delivered:
            name, conf, how = slug, 1.0, "exact"
        else:
            pref = [s for s in stems if slug.startswith(s) or s.startswith(slug)]
            if pref:
                name = max(pref, key=len)
                conf, how = 0.9, "prefix"
            else:
                best = max(stems, key=lambda s: jaccard(row["title_tokens"], norm_tokens(s)),
                           default=None)
                j = jaccard(row["title_tokens"], norm_tokens(best)) if best else 0.0
                if best and j >= a.jaccard:
                    name, conf, how = best, j, "jaccard"
        if not name:
            unmatched.append({"slug": slug, "views": row["views"], "title": row["title"]})
            continue
        d = delivered[name]
        feats = features(d["span"], clip_words(d["ctx"]))
        matched.append({
            "csv_slug": slug, "delivered": name, "match": how, "match_conf": round(conf, 3),
            "work_id": d["work_id"], "views": row["views"], "ctr": row["ctr"],
            "avd_sec": row["avd_sec"], "avd_frac": row["avd_frac"],
            "duration": row["duration"], "features": feats,
        })

    # outcomes (priority: retention proxy, then views)
    OUTCOMES = {
        "avd_frac": [m["avd_frac"] for m in matched],
        "avd_sec": [m["avd_sec"] for m in matched],
        "log_views": [math.log1p(m["views"]) for m in matched],
        "ctr": [m["ctr"] for m in matched],
    }
    feat_names = sorted({k for m in matched for k in m["features"] if not k.startswith("_")})

    results = {}
    for oc, yv in OUTCOMES.items():
        rows = []
        for fn in feat_names:
            xv = [m["features"].get(fn, float("nan")) for m in matched]
            r = spearman_boot(xv, yv, a.boot, a.seed + hash(fn + oc) % 10_000)
            r["feature"] = fn
            rows.append(r)
        passed = bh_fdr([r["p"] for r in rows], q=0.10)
        for j, r in enumerate(rows):
            r["fdr_pass"] = j in passed
        results[oc] = sorted(rows, key=lambda r: (math.isnan(r["rho"]), -abs(r["rho"])))

    # claim verdicts on the PRIMARY outcome (avd_frac), with cross-outcome reversal flags
    prim = {r["feature"]: r for r in results["avd_frac"]}
    views = {r["feature"]: r for r in results["log_views"]}
    verdicts = []
    for fn, claim in ADVICE_CLAIM.items():
        r = prim.get(fn)
        if not r or math.isnan(r["rho"]):
            continue
        lo, hi = r["ci"]
        excl0 = (lo > 0) or (hi < 0)
        obs = 1 if r["rho"] > 0 else -1
        if excl0:
            verdict = "SUPPORTED" if obs == claim else "CONTRADICTS — prune candidate"
        else:
            verdict = "unsupported (CI crosses 0; small-n)"
        vr = views.get(fn, {})
        rev = (not math.isnan(vr.get("rho", float("nan"))) and abs(r["rho"]) >= 0.25
               and abs(vr["rho"]) >= 0.25 and (r["rho"] > 0) != (vr["rho"] > 0))
        verdicts.append({
            "feature": fn, "claimed_sign": claim, "rho_retention": r["rho"],
            "ci_retention": r["ci"], "rho_views": vr.get("rho"), "verdict": verdict,
            "reverses_vs_views": bool(rev),
        })
    verdicts.sort(key=lambda v: (0 if "CONTRADICTS" in v["verdict"]
                                 else 1 if v["verdict"] == "SUPPORTED" else 2,
                                 -abs(v["rho_retention"])))

    report = {
        "csv": a.csv, "n_csv_videos": len(csvrows), "n_matched": len(matched),
        "n_unmatched": len(unmatched), "unmatched": sorted(unmatched, key=lambda u: -u["views"]),
        "bootstrap_B": a.boot, "fdr_q": 0.10,
        "primary_outcome": "avd_frac (retention proxy = avg view duration / clip duration)",
        "note": "Observational, small-n, confounded (title/thumbnail/topic/posting-time). "
                "Prunes anti-correlated §9 claims; never confirms the corpus (that is Tier 2).",
        "claim_verdicts": verdicts, "outcomes": results, "matched": matched,
    }
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump(report, open(a.out + ".json", "w"), indent=2)
    write_md(report, a.out + ".md")
    print(f"matched {len(matched)}/{len(csvrows)} CSV videos; wrote {a.out}.json + .md")


def write_md(rep, path):
    L = ["# T3 Retrospective — advice features vs real audience (own catalog)\n",
         f"*Source CSV:* `{os.path.basename(rep['csv'])}` · "
         f"matched **{rep['n_matched']}/{rep['n_csv_videos']}** videos "
         f"({rep['n_unmatched']} unmatched) · bootstrap B={rep['bootstrap_B']} · "
         f"BH-FDR q={rep['fdr_q']}\n",
         f"> {rep['note']}\n",
         f"> **Primary outcome:** {rep['primary_outcome']}. "
         "ρ>0 = feature tracks higher retention; ρ<0 = anti-correlated (prune candidate). "
         "`✓` = survives FDR; bracket = bootstrap 95% CI.\n"]
    L.append("\n## §9 claim verdicts (primary outcome `avd_frac`)\n")
    L.append("| advice feature | corpus claims | ρ retention | 95% CI | verdict | reverses vs views? |")
    L.append("|---|:--:|---:|---|---|:--:|")
    for v in rep["claim_verdicts"]:
        sign = "↑ helps" if v["claimed_sign"] > 0 else "↓ hurts"
        ci = f"[{v['ci_retention'][0]:+.2f}, {v['ci_retention'][1]:+.2f}]"
        L.append(f"| {v['feature']} | {sign} | {v['rho_retention']:+.3f} | {ci} | "
                 f"{v['verdict']} | {'⚠ yes' if v['reverses_vs_views'] else ''} |")
    L.append("\n*Only CONTRADICTS rows are actionable now (prune from `advice.md` before Tier 2). "
             "SUPPORTED rows survive; `unsupported` rows are simply underpowered at this n — "
             "neither kept nor cut on this evidence. ⚠ reversal = the feature helps one outcome "
             "and hurts another → transfer-gap risk, do not rely on it.*\n")
    for oc, rows in rep["outcomes"].items():
        L.append(f"\n## Outcome: `{oc}`\n")
        L.append("| feature | ρ | 95% CI | n | FDR✓ | P(ρ>0) |")
        L.append("|---|---:|---|---:|:--:|---:|")
        for r in rows:
            if math.isnan(r["rho"]):
                continue
            ci = f"[{r['ci'][0]:+.2f}, {r['ci'][1]:+.2f}]"
            mark = "✓" if r.get("fdr_pass") else ""
            L.append(f"| {r['feature']} | {r['rho']:+.3f} | {ci} | {r['n']} | {mark} | "
                     f"{r['frac_pos']:.2f} |")
    if rep["unmatched"]:
        L.append("\n## Unmatched CSV videos (no delivered-file join)\n")
        for u in rep["unmatched"]:
            L.append(f"- [{int(u['views'])} v] {u['slug']}")
    L.append("\n---\n*Interpretation:* a §9 claim is a **prune candidate** when its feature's "
             "CI excludes 0 in the WRONG direction on the primary outcome (e.g. a positive-claimed "
             "feature with ρ<0, CI not crossing 0). A claim with CI crossing 0 is simply unsupported "
             "here — small-n; it neither holds nor fails. Tier 2 (gold set) is the confirmatory test.\n")
    open(path, "w").write("\n".join(L))


if __name__ == "__main__":
    main()
