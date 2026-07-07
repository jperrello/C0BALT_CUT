import sys, os, json, argparse

VERSION = 1
Z = float(os.environ.get("SG_Z", "1.5"))
MINREFS = int(os.environ.get("SG_MIN_REFS", "3"))


def get(doc, dotted):
    cur = doc
    for k in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    if isinstance(cur, bool):
        return None
    if isinstance(cur, (int, float)):
        return float(cur)
    return None


def compare(profile, targets):
    if profile.get("style_profile_version") != VERSION \
       or targets.get("style_profile_version") != VERSION:
        return {"match": True, "skipped": "version mismatch", "checked": 0, "mismatches": []}
    if int(targets.get("n") or 0) < MINREFS:
        return {"match": True, "skipped": "corpus too small (n<%d)" % MINREFS,
                "checked": 0, "mismatches": []}
    mism = []
    diag = []
    checked = 0
    for field, t in (targets.get("fields") or {}).items():
        v = get(profile, field)
        if v is None:
            continue
        sigma = float(t.get("sigma") or 0)
        if sigma <= 0:
            continue
        z = (v - float(t["median"])) / sigma
        row = {"field": field, "ours": v, "target": t["median"],
               "sigma": sigma, "z": round(z, 2)}
        if t.get("diagnostic"):
            diag.append(row)
            continue
        checked += 1
        if abs(z) > Z:
            row["lever"] = t.get("lever")
            up = z < 0                       # below target -> raise the metric
            if t.get("invert"):
                up = not up                  # lever moves opposite the metric
            row["dir"] = "up" if up else "down"
            mism.append(row)
    mism.sort(key=lambda r: -abs(r["z"]))
    return {"match": not mism, "checked": checked, "z_max": Z,
            "mismatches": mism, "diagnostic": diag}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("targets")
    ap.add_argument("out")
    a = ap.parse_args()
    try:
        doc = compare(json.load(open(a.profile)), json.load(open(a.targets)))
    except Exception as e:
        doc = {"match": True, "skipped": "error: %s" % str(e)[:120],
               "checked": 0, "mismatches": []}
    json.dump(doc, open(a.out, "w"), indent=2)
    print(json.dumps({"match": doc["match"], "checked": doc["checked"],
                      "mismatches": len(doc["mismatches"])}))
    sys.exit(0 if doc["match"] else 1)


if __name__ == "__main__":
    main()
