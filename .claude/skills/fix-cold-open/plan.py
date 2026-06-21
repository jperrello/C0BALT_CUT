import sys, os, json, argparse


def load(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        return json.load(open(path))
    except Exception:
        return None


def routes(grade):
    fr = grade.get("fix_routes")
    if isinstance(fr, list):
        return [str(x) for x in fr]
    return []


def shot0kind(fill):
    if not fill:
        return None
    shots = fill.get("shots") or []
    if not shots:
        return None
    return shots[0].get("kind")


# broll picks overlapping [0, guard] are the cold-open cutaways that bury the
# face. Truncate = drop them outright (a pick that STARTS inside the guard is
# replaced by the speaker; a pick that merely ends inside it is also dropped
# since clearing the whole guard window is the goal).
def truncateplan(plan, guard):
    picks = plan.get("picks", []) or []
    kept, dropped = [], []
    for p in picks:
        t0 = float(p.get("t0", 9e9))
        t1 = float(p.get("t1", 0))
        if t0 <= guard and t1 > 0:
            dropped.append(p)
            continue
        kept.append(p)
    out = dict(plan)
    out["picks"] = kept
    return out, dropped


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")

    r = sub.add_parser("routes")
    r.add_argument("grade")

    s0 = sub.add_parser("shot0")
    s0.add_argument("fill")

    tr = sub.add_parser("truncate")
    tr.add_argument("plan")
    tr.add_argument("out")
    tr.add_argument("guard", type=float)

    a = ap.parse_args()

    if a.cmd == "routes":
        g = load(a.grade) or {}
        print("\n".join(routes(g)))
        return

    if a.cmd == "shot0":
        print(shot0kind(load(a.fill)) or "")
        return

    if a.cmd == "truncate":
        plan = load(a.plan) or {"picks": []}
        guard = a.guard
        out, dropped = truncateplan(plan, guard)
        with open(a.out, "w") as f:
            json.dump(out, f, indent=2)
        # report dropped windows for the .sh to log + record in .fix.json
        print(json.dumps([{"t0": float(p.get("t0", 0)), "t1": float(p.get("t1", 0)),
                           "clip_path": p.get("clip_path", "")} for p in dropped]))
        return

    ap.error("no command")


if __name__ == "__main__":
    main()
