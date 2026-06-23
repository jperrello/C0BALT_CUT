#!/usr/bin/env python3
# Learn GO/HOLD topic verdicts from a YouTube Studio "Table data.csv" export and
# rewrite the managed blocks of topics.scorelist + niches.txt.
# argv: <table-csv> <scorelist-path> <niches-path> <scores-json-out>
import csv, json, os, re, statistics, sys

table, scorelist_path, niches_path, scores_out = sys.argv[1:5]

GO_VIEWS = int(os.environ.get("AF_GO_VIEWS", "600"))
HOLD_VIEWS = int(os.environ.get("AF_HOLD_VIEWS", "60"))
GO_MIN_N = int(os.environ.get("AF_GO_MIN_N", "3"))      # winners need consistency
HOLD_MIN_N = int(os.environ.get("AF_HOLD_MIN_N", "2"))  # dead-is-dead needs less
GO_CTR = float(os.environ.get("AF_GO_CTR", "5.0"))

SCORE_SENTINEL = "# ==== AUTO (analytics-feedback) — regenerated each run; hand-edit ONLY above this line ===="
NICHE_SENTINEL = "# ==== AUTO niches (analytics-feedback) — proven-winner expansions, regenerated each run ===="

# known entities -> (scorelist pattern matching spaced-or-hyphenated, title-find regex, niche search query or None)
LEX = [
    ("brian[ -]?cox", r"brian\s*cox|briancox", "brian cox interview clip"),
    ("huberman", r"huberman", None),
    ("dopamine", r"dopamine", None),
    ("neuroscien", r"neuroscien", None),
    ("mcconaughey", r"mcconaughey", "matthew mcconaughey interview"),
    ("caseoh", r"caseoh", "caseoh podcast highlights"),
    ("mrbeast", r"mr\s*beast|mrbeast", None),
    ("joe[ -]?rogan", r"joe\s*rogan", "joe rogan experience clips"),
    ("theo[ -]?von", r"theo\s*von", None),
    ("black[ -]?hole", r"black\s*hole|blackhole", "black hole physics explained"),
    (r"\bspace\b", r"\bspace\b", "space astronomy podcast"),
    ("galax", r"galax", None),
    ("universe", r"universe", "universe cosmology explained"),
    ("krauss", r"krauss", "lawrence krauss lecture interview"),
    ("sean[ -]?carroll", r"sean\s*carroll", "sean carroll mindscape podcast"),
    ("discipline", r"discipline", None),
    ("habit", r"habit", None),
    (r"\bbrain\b", r"\bbrain\b", None),
    (r"\bfocus\b", r"\bfocus\b", None),
    ("exercis", r"exercis", None),
    (r"\bphone\b", r"\bphone\b", None),
    # loser cluster
    (r"\bai\b|aivideo", r"\bai\b|aivideo|a\.i\.", None),
    ("chatgpt", r"chatgpt", None),
    ("software", r"software", None),
    ("coding|coder", r"coding|coder", None),
    ("dev team|developer", r"dev\s*team|developer", None),
    ("productivity", r"productivity", None),
    ("scaffolding", r"scaffolding", None),
    ("ozempic", r"ozempic", None),
    ("starlink", r"starlink|starlight", None),
    (r"\belon\b", r"\belon\b", None),
]

STOP = set("""the and for with why how what his her real only says this that from your you are was not who she him they them their our out get got new now one two has had can will just why when where about into over more most than then them very much many lot why edit edits shorts short podcast podcasts clip clips full interview interviews episode deep theory viral mindset mindblown motivation selfimprovement selfcare funny interesting youdontknow youtubeadvice fyp space life love mind money m/s""".split())


def num(x, d=0.0):
    try:
        return float(str(x).replace(",", "").strip())
    except (ValueError, AttributeError):
        return d


def rows():
    with open(table, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            vid = (r.get("Content") or "").strip()
            if not vid or vid.lower() == "total":
                continue
            views = num(r.get("Views"))
            if views <= 0:
                continue
            dur = num(r.get("Duration"))
            wh = num(r.get("Watch time (hours)"))
            ctr = num(r.get("Impressions click-through rate (%)"))
            ret = 0.0
            if dur > 0 and views > 0:
                ret = min(1.5, (wh * 3600.0 / views) / dur)
            yield {"title": (r.get("Video title") or "").lower(), "views": views,
                   "ctr": ctr, "ret": ret, "wh": wh}


def auto_tokens(title):
    for w in re.split(r"[^a-z0-9]+", title):
        if len(w) >= 4 and not w.isdigit() and w not in STOP:
            yield w


def main():
    vids = list(rows())
    if not vids:
        print("analytics-feedback: no usable rows in CSV", file=sys.stderr)
        sys.exit(1)

    # accumulate per token: keyed by scorelist-pattern; remember a label + niche
    acc = {}   # key -> {"views":[], "ctr":[], "ret":[], "wh":float, "niche", "lex", "vids":set}

    def bucket(key, niche, lex, i, v):
        a = acc.setdefault(key, {"views": [], "ctr": [], "ret": [], "wh": 0.0, "niche": None, "lex": False, "vids": set()})
        a["views"].append(v["views"]); a["ctr"].append(v["ctr"]); a["ret"].append(v["ret"])
        a["wh"] += v["wh"]; a["vids"].add(i)
        a["lex"] = a["lex"] or lex
        if niche and not a["niche"]:
            a["niche"] = niche

    for i, v in enumerate(vids):
        for pat, find, niche in LEX:
            if re.search(find, v["title"]):
                bucket(pat, niche, True, i, v)
        for tok in set(auto_tokens(v["title"])):
            bucket(tok, None, False, i, v)

    scored = []
    for key, a in acc.items():
        n = len(a["views"])
        med = statistics.median(a["views"])
        mean_ctr = statistics.mean(a["ctr"]) if a["ctr"] else 0.0
        med_ret = statistics.median(a["ret"]) if a["ret"] else 0.0
        if n >= GO_MIN_N and med >= GO_VIEWS and mean_ctr >= GO_CTR:
            verdict = "GO"
        elif n >= HOLD_MIN_N and med <= HOLD_VIEWS:
            verdict = "HOLD"
        else:
            verdict = "neutral"
        scored.append({
            "token": key, "verdict": verdict, "n": n,
            "median_views": round(med), "mean_views": round(statistics.mean(a["views"])),
            "min_views": round(min(a["views"])), "max_views": round(max(a["views"])),
            "mean_ctr": round(mean_ctr, 2), "median_retention": round(med_ret, 2),
            "total_watch_hours": round(a["wh"], 2), "lexicon": a["lex"], "niche": a["niche"],
            "suppressed": False, "_vids": a["vids"],
        })

    # coverage-dedup: a non-lexicon token whose video set is covered by a lexicon
    # token of the same verdict is a redundant alias (#blackhole vs black[ -]?hole)
    lex_sets = [(s["token"], s["_vids"], s["verdict"]) for s in scored if s["lexicon"]]
    for s in scored:
        if s["lexicon"]:
            continue
        for ltok, lset, lv in lex_sets:
            if lv == s["verdict"] and s["_vids"] <= lset:
                s["suppressed"] = True
                s["suppressed_by"] = ltok
                break
    for s in scored:
        s.pop("_vids", None)
    scored.sort(key=lambda s: (-{"GO": 2, "neutral": 1, "HOLD": 0}[s["verdict"]], -s["median_views"]))

    go = [s for s in scored if s["verdict"] == "GO" and not s["suppressed"]]
    hold = [s for s in scored if s["verdict"] == "HOLD" and not s["suppressed"]]

    # ---- rewrite topics.scorelist managed block, preserving the manual head ----
    manual = ""
    if os.path.isfile(scorelist_path):
        manual = open(scorelist_path, encoding="utf-8").read().split(SCORE_SENTINEL)[0].rstrip() + "\n"
    manual_low = manual.lower()
    lines = [manual, SCORE_SENTINEL,
             f"# derived from {os.path.basename(os.path.dirname(table))} | "
             f"{len(vids)} videos | GO>= {GO_VIEWS}v&{GO_CTR}%CTR&n>={GO_MIN_N}, HOLD<= {HOLD_VIEWS}v&n>={HOLD_MIN_N}"]
    conflicts = []
    for s in go + hold:
        tok = s["token"]
        # skip if the manual head already states the same verdict for this exact token
        if re.search(rf"(?im)^\s*{re.escape(s['verdict'])}\s+{re.escape(tok)}\s*$", manual):
            continue
        opp = "HOLD" if s["verdict"] == "GO" else "GO"
        if re.search(rf"(?im)^\s*{re.escape(opp)}\s+{re.escape(tok)}\s*$", manual):
            conflicts.append((tok, opp, s["verdict"]))
        # evidence MUST be a separate comment line — schedule.py treats everything
        # after the verdict on a rule line as part of the regex pattern.
        lines.append(f"# {tok}  n={s['n']} med={s['median_views']}v ctr={s['mean_ctr']}% ret={s['median_retention']}")
        lines.append(f"{s['verdict']} {tok}")
    open(scorelist_path, "w", encoding="utf-8").write("\n".join(lines).rstrip() + "\n")

    # ---- expand niches.txt with proven-winner search queries (additive) ----
    nman = ""
    if os.path.isfile(niches_path):
        nman = open(niches_path, encoding="utf-8").read().split(NICHE_SENTINEL)[0].rstrip() + "\n"
    have = nman.lower()
    extra = []
    for s in go:
        q = s["niche"]
        if q and q.lower() not in have and not any(q.lower() in ln for ln in have.splitlines()):
            extra.append(q)
            have += q.lower() + "\n"
    nlines = [nman, NICHE_SENTINEL] + extra
    open(niches_path, "w", encoding="utf-8").write("\n".join(nlines).rstrip() + "\n")

    json.dump({"source_csv": table, "videos": len(vids),
               "thresholds": {"GO_VIEWS": GO_VIEWS, "HOLD_VIEWS": HOLD_VIEWS,
                              "GO_MIN_N": GO_MIN_N, "HOLD_MIN_N": HOLD_MIN_N, "GO_CTR": GO_CTR},
               "conflicts": [{"token": t, "manual": m, "data": d} for t, m, d in conflicts],
               "tokens": scored}, open(scores_out, "w"), indent=2)

    print(f"analytics-feedback: {len(vids)} videos -> {len(go)} GO, {len(hold)} HOLD, "
          f"{len(extra)} niche expansions, {len(conflicts)} manual-conflict(s)")
    for s in go[:8]:
        print(f"  GO   {s['token']:<18} med={s['median_views']:>5}v ctr={s['mean_ctr']:>5}% n={s['n']}")
    for s in hold[:8]:
        print(f"  HOLD {s['token']:<18} med={s['median_views']:>5}v ctr={s['mean_ctr']:>5}% n={s['n']}")
    if conflicts:
        print("  conflicts (data overrides manual; HOLD wins in schedule-drip):")
        for t, m, d in conflicts:
            print(f"    {t}: manual={m} data={d}")


main()
