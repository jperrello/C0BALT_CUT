import os, sys, json

# gate 2 oracle: a kept fix must (a) not regress the proxy grade AND (b) clear
# the specific grade.json signal the reviewer flagged. This encodes the POLARITY
# of every grade.json signal + hard_cap so "cleared" means the same thing the
# grade-clip contract means (SELECTION-SUITE-CONTRACT.md).

HARDCAPS = {"letterbox", "face_withheld", "credit_at_open", "blocking_card", "dead_tail"}

# numeric signals where LOWER is better; cleared iff value <= budget
NUM_MAX = {
    "max_residual_silence": float(os.environ.get("GRADE_SILENCE_SEC", "0.8")),
    "first_payoff_offset": float(os.environ.get("GRADE_PAYOFF_SEC", "3.0")),
    "first_visual_change_sec": float(os.environ.get("GRADE_FIRST_CHANGE_SEC", "3.0")),
    "longest_static_gap": float(os.environ.get("GRADE_STATIC_GAP_SEC", "5.0")),
}


def num(v):
    try:
        return float(v)
    except Exception:
        return None


def cleared(new, signal):
    sig = (signal or "").strip()
    if not sig:
        return True                       # no flagged signal -> grade delta is the only gate
    signals = new.get("signals") or {}
    caps = set(new.get("hard_caps") or [])

    # a hard-cap named directly: cleared iff absent from new.hard_caps
    if sig in HARDCAPS:
        return sig not in caps

    # boolean signals with known polarity
    if sig == "frame1_is_face":
        return signals.get("frame1_is_face") is True and "face_withheld" not in caps
    if sig == "letterbox_bars":
        return not bool(signals.get("letterbox_bars")) and "letterbox" not in caps
    if sig == "credit_lit_at_open":
        return not bool(signals.get("credit_lit_at_open")) and "credit_at_open" not in caps

    # numeric, lower-is-better with a budget
    if sig in NUM_MAX:
        v = num(signals.get(sig))
        if v is None:
            return False                  # unknown value -> conservative fail
        return v <= NUM_MAX[sig]

    # numeric, higher-is-better
    if sig == "opening_caption_words":
        v = num(signals.get(sig))
        if v is None:
            return False
        return v >= float(os.environ.get("GRADE_MIN_CAPTION_WORDS", "3"))
    if sig == "terminal_loop_score":
        v = num(signals.get(sig))
        if v is None:
            return False
        return v >= float(os.environ.get("FSF_LOOP_MIN", "0.4"))

    # unknown signal -> conservative fail (never keep a fix we can't verify)
    return False


def passes(prev, new, signal):
    pg = num(prev.get("grade"))
    ng = num(new.get("grade"))
    if pg is None or ng is None:
        return False
    if ng < pg:
        return False
    return cleared(new, signal)


def loadjson(path):
    try:
        return json.load(open(path))
    except Exception:
        return None


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: check_grade.py <prev_grade.json> <new_grade.json> [signal]\n")
        sys.exit(2)
    prev = loadjson(sys.argv[1])
    new = loadjson(sys.argv[2])
    signal = sys.argv[3] if len(sys.argv) > 3 else ""
    if not isinstance(prev, dict) or not isinstance(new, dict):
        sys.stderr.write("check_grade: unreadable grade json -> reject\n")
        sys.exit(1)
    ok = passes(prev, new, signal)
    sys.stderr.write(json.dumps({
        "prev_grade": prev.get("grade"), "new_grade": new.get("grade"),
        "signal": signal or None, "cleared": cleared(new, signal), "pass": ok}) + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
