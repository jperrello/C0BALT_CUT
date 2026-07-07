import os, json, argparse


def loadjson(p):
    if not p or not os.path.isfile(p):
        return None
    try:
        return json.load(open(p))
    except Exception:
        return None


def readtext(p):
    if not p or not os.path.isfile(p):
        return ""
    try:
        return open(p).read().strip()
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("framesjson")
    ap.add_argument("--grade", default="")
    ap.add_argument("--transcript", default="")
    ap.add_argument("--dur", type=float, default=0.0)
    a = ap.parse_args()

    fi = loadjson(a.framesjson) or {}
    frames = fi.get("frames", [])
    dur = a.dur or float(fi.get("duration", 0.0) or 0.0)
    framemap = " ".join("#%d=%.1fs" % (f.get("k", 0), f.get("t", 0.0)) for f in frames)

    grade = loadjson(a.grade) or {}
    sig = grade.get("signals") or {}
    gradeline = "proxy grade %s/%s; hard_caps=%s; signals=%s" % (
        grade.get("grade"), grade.get("tier"),
        ",".join(grade.get("hard_caps") or []) or "none",
        json.dumps(sig))

    tx = loadjson(a.transcript)
    script = "(transcript unavailable)"
    if tx and isinstance(tx.get("segments"), list):
        lines = []
        for s in tx["segments"]:
            t0 = float(s.get("t0", 0.0))
            t1 = float(s.get("t1", 0.0))
            txt = str(s.get("text", "")).strip()
            if txt:
                lines.append("[%.1f-%.1f] %s" % (t0, t1, txt))
        if lines:
            script = "\n".join(lines)

    print(f"""You are the FIRST-SPAN REVIEWER at a hard pre-fanout gate. The pipeline has produced ONLY span 0 of this source so far; every later span will render on the SAME skill code. Your job: decide whether span 0 has a SYSTEMIC defect — one the code will repeat on every later span — or is clean enough to fan out.

You are given a demo recording of span 0's review page, sampled into ONE contact sheet — a 4-column row-major grid of frames across the {dur:.1f}s recording. READ IT WITH YOUR READ TOOL:
  {a.sheet}
Each cell is labelled with its timestamp. Frame index -> time: {framemap}
Each cell shows the 9:16 player mid-playthrough AND the signals panel beside it — the clip and its diagnosis travel together, so judge what you actually see (the framing, the burned captions, the b-roll, the cold open) against the flagged signals.

GRADE / SIGNALS (from grade-clip, the swipe-gate proxy):
{gradeline}

SPOKEN SCRIPT (approx clip-time):
{script}

Only flag a SYSTEMIC defect — a root-cause fault in a skill's logic or a default that WILL recur on later spans of this source:
- COLD OPEN / SWIPE GATE: is frame 1 the speaker's face, or buried behind b-roll / a mis-crop / a blocking card? (grade signal frame1_is_face)
- WRONG-PERSON FRAMING: is the hero-frame a silent listener instead of the talker? (fill-vertical speaker bias)
- LETTERBOX / BARS: any pillarbox/letterbox instead of a full-bleed punch-in? (letterbox_bars)
- CAPTION TIMING: burned captions out of sync, overlapping, or wrong words?
- B-ROLL FIT: a cutaway tonally wrong / literal-but-wrong for what's said?
- MUSIC BALANCE: does the bed drown the speech?
- DEAD TAIL / FLAT HOOK: dead air after the payoff, or a throat-clearing open with no curiosity gap?

Do NOT flag a per-clip cosmetic fluke that would not recur — those stay downstream QA's job. A clean span 0 returns defect=false. Do not invent a defect to look thorough.

If you flag a defect, map it to the grade.json SIGNAL it corresponds to when one applies (frame1_is_face | letterbox_bars | credit_lit_at_open | max_residual_silence | longest_static_gap | first_payoff_offset | first_visual_change_sec), else null; and name WHERE the root cause lives (the implicated skill/file).

Reply with ONLY one JSON object, no prose, no code fences:
{{"defect": true|false, "defect_class": "cold_open|wrong_person|letterbox|caption_mistime|broll_wrong|hot_music|dead_tail|flat_hook|other", "signal": "<grade.json signal or null>", "where": "<implicated skill/file>", "rationale": "<one line: what is wrong and why it is systemic>"}}""")


if __name__ == "__main__":
    main()
