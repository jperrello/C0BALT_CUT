import sys, json

EPS = 0.15


def zmap(verdict):
    out = {}
    for key in ("mismatches", "diagnostic"):
        for r in verdict.get(key, []):
            out[r["field"]] = abs(r.get("z", 0.0))
    return out


def passes(prev, new):
    if new.get("match"):
        return True
    pz = zmap(prev)
    nz = zmap(new)
    improved = False
    for f, z in pz.items():
        n = nz.get(f)
        if n is None:
            continue
        if n > z + EPS:
            return False                    # some checked field got worse
        if n < z - EPS:
            improved = True
    prevm = {r["field"] for r in prev.get("mismatches", [])}
    newm = {r["field"] for r in new.get("mismatches", [])}
    if newm - prevm:
        return False                        # a new mismatch appeared
    if prevm - newm:
        improved = True
    return improved


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: accept.py <prev_verdict.json> <new_verdict.json>\n")
        sys.exit(2)
    try:
        prev = json.load(open(sys.argv[1]))
        new = json.load(open(sys.argv[2]))
    except Exception:
        sys.stderr.write("accept: unreadable verdict -> reject\n")
        sys.exit(1)
    ok = passes(prev, new)
    sys.stderr.write(json.dumps({"pass": ok, "prev_mismatches": len(prev.get("mismatches", [])),
                                 "new_mismatches": len(new.get("mismatches", []))}) + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
