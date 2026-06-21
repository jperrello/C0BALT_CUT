import sys, os, json, glob, re, shutil
from datetime import date, timedelta

root = sys.argv[1]
outdir = sys.argv[2]
scorelist = sys.argv[3]
today = sys.argv[4]
posts = int(os.environ.get("POSTS_PER_DAY", "1"))
cap = int(os.environ.get("MAX_PER_SOURCE_PER_DAY", "1"))
horizon = int(os.environ.get("DRIP_HORIZON_DAYS", "14"))
minup = int(os.environ.get("GRADE_MIN_UPLOAD", "60"))

stage = os.path.join(outdir, "_toupload")
skip = ("_preview", "_toupload", "_triage")

RERUN = "rerun_recommended"


def rules(path):
    out = []
    if not os.path.isfile(path):
        return out
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        out.append((parts[0].upper(), parts[1].lower()))
    return out


def hits(rules, hay):
    for v, pat in rules:
        try:
            hit = re.search(pat, hay) is not None
        except re.error:
            hit = pat in hay
        if hit:
            yield v, pat


# HOLD is a denylist and WINS over an incidental GO substring (e.g. "focus" inside
# "stay-focused" on a productivity death-source). Any HOLD match -> HOLD; else the
# first GO match; else default HOLD (conservative).
def verdict(rules, slug, title):
    hay = (slug + " " + title).lower()
    matches = list(hits(rules, hay))
    for v, pat in matches:
        if v == "HOLD":
            return "HOLD", pat
    for v, pat in matches:
        if v == "GO":
            return "GO", pat
    return "HOLD", None


def hashtags(slug, title, pat):
    seen = []
    for tok in [pat] if pat else []:
        for w in re.split(r"[^a-z0-9]+", tok.lower()):
            if len(w) >= 3 and w not in seen:
                seen.append(w)
    for w in re.split(r"[^a-z0-9]+", slug.lower()):
        if len(w) >= 4 and w not in seen and not w.isdigit():
            seen.append(w)
        if len(seen) >= 4:
            break
    base = ["shorts", "fyp"]
    tags = ["#" + w for w in seen[:4]] + ["#" + b for b in base]
    return tags


def title(clip, slug):
    name = os.path.splitext(os.path.basename(clip))[0]
    name = re.sub(r"-\d+(\.\d+)?x$", "", name)
    name = re.sub(r"-\d+$", "", name)
    return name.replace("-", " ").strip().lower()


def tokens(t):
    return set(w for w in re.split(r"[^a-z0-9]+", t.lower()) if len(w) >= 3)


def loadlog(outdir):
    posted = set()
    for name in ("upload-log.json",):
        p = os.path.join(outdir, name)
        if not os.path.isfile(p):
            continue
        try:
            data = json.load(open(p))
        except Exception:
            continue
        items = data if isinstance(data, list) else data.get("uploaded", data.get("posted", []))
        if isinstance(items, dict):
            items = list(items.keys())
        for it in items or []:
            val = it.get("clip", it.get("path", it.get("title", ""))) if isinstance(it, dict) else it
            if val:
                posted.add(str(val))
    return posted


def posted_match(posted, clip, ttl):
    base = os.path.basename(clip)
    for p in posted:
        if p == clip or os.path.basename(p) == base:
            return True
        if p.lower().strip() == ttl:
            return True
    return False


def schedulable(g):
    tier = g.get("tier")
    caps = g.get("hard_caps") or []
    if tier == "GOLD" and not caps:
        return True
    if g.get("grade", 0) >= minup and not caps:
        return True
    return False


def collect():
    out = []
    for p in sorted(glob.glob(os.path.join(outdir, "**", "*.grade.json"), recursive=True)):
        if any(s in p for s in skip) or "/source/" in p or os.sep + "source" + os.sep in p:
            continue
        try:
            g = json.load(open(p))
        except Exception:
            continue
        clip = g.get("clip") or p[: -len(".grade.json")] + ".mp4"
        src = g.get("source") or os.path.basename(os.path.dirname(p))
        g["_clip"] = clip
        g["_src"] = src
        out.append(g)
    return out


def main():
    rs = rules(scorelist)
    posted = loadlog(outdir)
    clips = collect()

    drops = []
    pool = []
    for g in clips:
        clip = g["_clip"]
        src = g["_src"]
        ttl = title(clip, src)
        if not schedulable(g):
            drops.append({"clip": clip, "reason": "not_schedulable", "tier": g.get("tier"), "grade": g.get("grade"), "hard_caps": g.get("hard_caps")})
            continue
        if posted_match(posted, clip, ttl):
            drops.append({"clip": clip, "reason": "already_posted"})
            continue
        v, pat = verdict(rs, src, ttl)
        pool.append({"clip": clip, "src": src, "grade": int(g.get("grade", 0)), "verdict": v, "pat": pat, "title": ttl})

    pool.sort(key=lambda c: (-c["grade"], c["src"], c["clip"]))

    kept = []
    for c in pool:
        dup = None
        for k in kept:
            if k["src"] != c["src"]:
                continue
            a, b = tokens(k["title"]), tokens(c["title"])
            if not a or not b:
                continue
            ov = len(a & b) / max(1, min(len(a), len(b)))
            if ov >= 0.7:
                dup = k
                break
        if dup:
            drops.append({"clip": c["clip"], "reason": "dedupe_near_identical", "kept": dup["clip"], "overlap_with": dup["title"]})
            continue
        kept.append(c)

    go = [c for c in kept if c["verdict"] == "GO"]
    hold = [c for c in kept if c["verdict"] == "HOLD"]

    start = date.fromisoformat(today)
    days = [start + timedelta(days=i) for i in range(horizon)]
    plan = {d.isoformat(): [] for d in days}

    def place(queue):
        for c in queue:
            for d in days:
                k = d.isoformat()
                if len(plan[k]) >= posts:
                    continue
                if sum(1 for x in plan[k] if x["src"] == c["src"]) >= cap:
                    continue
                plan[k].append(c)
                c["_placed"] = True
                break

    # GO clips fill days first; HOLD only backfills days that would otherwise be dark.
    place(go)

    dark = [d for d in days if not plan[d.isoformat()]]
    backfill = []
    for c in hold:
        if not dark:
            break
        for d in list(dark):
            k = d.isoformat()
            if sum(1 for x in plan[k] if x["src"] == c["src"]) >= cap:
                continue
            plan[k].append(c)
            c["_placed"] = True
            backfill.append({"clip": c["clip"], "date": k})
            dark.remove(d)
            break

    for c in go + hold:
        if not c.get("_placed"):
            drops.append({"clip": c["clip"], "reason": "horizon_full", "verdict": c["verdict"], "grade": c["grade"]})

    gaps = [d.isoformat() for d in days if not plan[d.isoformat()]]

    # idempotent rebuild of the staging tree
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(stage, exist_ok=True)

    sched = {"generated": today, "horizon_days": horizon, "posts_per_day": posts, "max_per_source_per_day": cap, "days": {}, "gap_warnings": gaps, "backfilled": backfill, "drops": drops}

    for d in days:
        k = d.isoformat()
        entries = plan[k]
        sched["days"][k] = []
        if not entries:
            continue
        ddir = os.path.join(stage, k)
        os.makedirs(ddir, exist_ok=True)
        meta_lines = []
        for c in entries:
            src_clip = c["clip"]
            if not os.path.isabs(src_clip):
                src_clip = os.path.join(root, src_clip)
            dest = os.path.join(ddir, os.path.basename(c["clip"]))
            if os.path.isfile(src_clip):
                shutil.copy2(src_clip, dest)
            tags = hashtags(c["src"], c["title"], c["pat"])
            meta_lines.append(c["title"])
            meta_lines.append(" ".join(tags))
            meta_lines.append("")
            sched["days"][k].append({"clip": c["clip"], "src": c["src"], "grade": c["grade"], "verdict": c["verdict"], "staged": os.path.relpath(dest, root), "hashtags": tags})
        open(os.path.join(ddir, "metadata.txt"), "w", encoding="utf-8").write("\n".join(meta_lines).rstrip() + "\n")

    json.dump(sched, open(os.path.join(stage, "schedule.json"), "w"), indent=2)

    print(f"schedule-drip: {sum(len(v) for v in plan.values())} clips staged across {horizon}d "
          f"({len([d for d in days if plan[d.isoformat()]])} days filled, {len(gaps)} dark), "
          f"{len(drops)} drops, {len(backfill)} backfilled")


main()
