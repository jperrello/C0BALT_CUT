import json, os, re, sys, time


def slug(meta, fallback):
    t = (meta.get("title") or meta.get("id") or meta.get("source_id") or "").strip()
    s = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:80]
    return s or fallback


def dirbytes(p):
    tot = 0
    for r, _, files in os.walk(p):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return tot


def datestr(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def entry(work, out, wid):
    d = os.path.join(work, wid)
    ing = os.path.join(d, "ingest.json")
    if not os.path.isfile(ing):
        return None
    try:
        meta = json.load(open(ing))
    except Exception:
        meta = {}
    s = slug(meta, wid)
    shorts = []
    odir = os.path.join(out, s)
    if os.path.isdir(odir):
        for f in sorted(os.listdir(odir)):
            if not f.endswith(".mp4") or f.startswith(".") or f.endswith(".orig.mp4"):
                continue
            grade = tier = None
            g = os.path.join(odir, f[:-4] + ".grade.json")
            if os.path.isfile(g):
                try:
                    gj = json.load(open(g))
                    grade, tier = gj.get("grade"), gj.get("tier")
                except Exception:
                    pass
            shorts.append({"name": f, "grade": grade, "tier": tier,
                           "path": os.path.relpath(os.path.join(odir, f))})
    marker = os.path.join(d, ".reaped")
    reaped_on = None
    if os.path.isfile(marker):
        try:
            reaped_on = (open(marker).read().strip().split() or [None])[0]
        except Exception:
            pass
    status = "reaped" if (reaped_on or not os.path.isfile(os.path.join(d, "source.mp4"))) else "active"
    return {
        "id": wid,
        "slug": s,
        "title": meta.get("title"),
        "url": meta.get("url"),
        "uploader": meta.get("uploader") or meta.get("channel"),
        "duration_sec": meta.get("duration"),
        "ingested": datestr(os.path.getmtime(ing)),
        "shorts": shorts,
        "shorts_count": len(shorts),
        "status": status,
        "reaped": reaped_on,
        "work_bytes": dirbytes(d),
    }


def load(p):
    try:
        return json.load(open(p))
    except Exception:
        return []


def write(p, data):
    tmp = p + ".tmp"
    json.dump(data, open(tmp, "w"), indent=2)
    os.replace(tmp, p)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "sync"
    work, out = os.environ["WORK_DIR"], os.environ["OUT_DIR"]
    ledger = os.path.join(work, "sources.json")

    if mode == "sync":
        rows = []
        for wid in sorted(os.listdir(work)):
            if not os.path.isdir(os.path.join(work, wid)):
                continue
            e = entry(work, out, wid)
            if e:
                rows.append(e)
        rows.sort(key=lambda r: r.get("ingested") or "", reverse=True)
        write(ledger, rows)
        active = sum(r["status"] == "active" for r in rows)
        reaped = sum(r["status"] == "reaped" for r in rows)
        gb = sum(r["work_bytes"] for r in rows) / 2**30
        print(f"sources-ledger: {len(rows)} sources ({active} active, {reaped} reaped, {gb:.1f}GB on disk) -> {ledger}")
        return

    if mode == "record":
        wid = sys.argv[2]
        e = entry(work, out, wid)
        if not e:
            print(f"sources-ledger: {wid} has no ingest.json, skip", file=sys.stderr)
            return
        rows = [r for r in load(ledger) if r.get("id") != wid]
        rows.append(e)
        rows.sort(key=lambda r: r.get("ingested") or "", reverse=True)
        write(ledger, rows)
        grades = [x["grade"] for x in e["shorts"] if isinstance(x.get("grade"), (int, float))]
        print(json.dumps({"id": wid, "title": e["title"], "slug": e["slug"], "url": e["url"],
                          "shorts_count": e["shorts_count"], "top_grade": (max(grades) if grades else None),
                          "status": e["status"]}))
        return

    print(f"sources-ledger: unknown mode {mode}", file=sys.stderr)
    sys.exit(2)


main()
