import sys, os, json, argparse

MAXMOVES = int(os.environ.get("SG_MAX_MOVES", "2"))

KNOBS = {
    "JUMP_CUT_SEG": {"default": 3.2, "step": 0.7, "min": 1.8, "max": 6.0, "mode": "mul"},
    "JUMP_CUT_MAX_GAP": {"default": 5.0, "step": 0.7, "min": 2.5, "max": 8.0, "mode": "mul"},
    "SPEED": {"default": 1.15, "step": 0.05, "min": 1.0, "max": 1.35, "mode": "add"},
    "SWITCH_SPACING": {"default": 5.0, "step": 0.7, "min": 3.0, "max": 10.0, "mode": "mul"},
}


def current(name, spec):
    try:
        return float(os.environ.get(name, spec["default"]))
    except Exception:
        return spec["default"]


def move(name, direction):
    spec = KNOBS.get(name)
    if not spec:
        return None
    cur = current(name, spec)
    if spec["mode"] == "mul":
        new = cur * spec["step"] if direction == "down" else cur / spec["step"]
    else:
        new = cur - spec["step"] if direction == "down" else cur + spec["step"]
    new = max(spec["min"], min(spec["max"], new))
    if abs(new - cur) < 1e-9:
        return None
    return round(new, 3)


def plan(verdict):
    out = {}
    for m in verdict.get("mismatches", []):
        lever = m.get("lever")
        if not lever or lever in out:
            continue
        v = move(lever, m.get("dir", "up"))
        if v is not None:
            out[lever] = v
        if len(out) >= MAXMOVES:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("verdict")
    ap.add_argument("env")
    a = ap.parse_args()
    try:
        moves = plan(json.load(open(a.verdict)))
    except Exception:
        moves = {}
    with open(a.env, "w") as f:
        for k, v in moves.items():
            f.write("export %s=%g\n" % (k, v))
    print(json.dumps({"moves": moves}))
    sys.exit(0 if moves else 1)


if __name__ == "__main__":
    main()
