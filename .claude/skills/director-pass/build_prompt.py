import sys, os, json, argparse


def loadjson(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        return json.load(open(path))
    except Exception:
        return None


def readtext(path):
    if not path or not os.path.isfile(path):
        return ""
    try:
        return open(path).read().strip()
    except Exception:
        return ""


# the finished clip is sped (default 1.25x) but the transcript/chunks are in the
# pre-speed clip-local timeline. scale text times INTO the finished timeline so
# the spoken words line up with the contact-sheet timestamps the reviewer sees.
def speed(chunks, dur):
    if not chunks or dur <= 0:
        return 1.0
    cs = chunks.get("chunks") or []
    if not cs:
        return 1.0
    end = max(float(c.get("t1", 0.0)) for c in cs)
    if end <= 0:
        return 1.0
    s = end / dur
    if s < 0.5 or s > 2.0:
        return 1.0
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("dur", type=float)
    ap.add_argument("sheet")
    ap.add_argument("framesjson")
    ap.add_argument("--transcript", default="")
    ap.add_argument("--chunks", default="")
    ap.add_argument("--fill", default="")
    ap.add_argument("--broll", default="")
    ap.add_argument("--cadence", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--mood", default="")
    ap.add_argument("--grade", default="")
    ap.add_argument("--mode", default="curative")
    ap.add_argument("--vol", default="0.17")
    ap.add_argument("--mindur", type=float, default=15.0)
    a = ap.parse_args()

    dur = a.dur
    title = readtext(a.title)
    mood = readtext(a.mood)
    chunks = loadjson(a.chunks)
    fi = loadjson(a.framesjson) or {}
    frames = fi.get("frames", [])
    sp = speed(chunks, dur)

    # spoken transcript, scaled into finished-clip time, as phrase lines
    lines = []
    if chunks:
        for c in (chunks.get("chunks") or []):
            t0 = float(c.get("t0", 0.0)) / sp
            t1 = float(c.get("t1", 0.0)) / sp
            txt = str(c.get("text", "")).strip()
            if txt:
                lines.append("[%.1f-%.1f] %s" % (t0, t1, txt))
    script = "\n".join(lines) or "(transcript unavailable)"

    # fill shot kinds (face / listener / saliency) scaled to finished time
    fill = loadjson(a.fill)
    shotline = ""
    if fill and fill.get("shots"):
        parts = []
        for s in fill["shots"]:
            parts.append("[%.1f-%.1f]%s" % (float(s.get("t0", 0)) / sp,
                                            float(s.get("t1", 0)) / sp,
                                            s.get("kind", "?")))
        shotline = " ".join(parts)

    # b-roll cutaway windows scaled to finished time (what footage, when)
    broll = loadjson(a.broll)
    brolline = ""
    if broll and broll.get("picks"):
        parts = []
        for p in broll["picks"]:
            parts.append("[%.1f-%.1f] %s" % (float(p.get("t0", 0)) / sp,
                                             float(p.get("t1", 0)) / sp,
                                             str(p.get("query", "")).strip() or "?"))
        brolline = "\n".join(parts)

    cad = loadjson(a.cadence)
    cadline = ""
    if cad and "max_gap" in cad:
        gw = cad.get("gap_window") or []
        cadline = "longest static stretch %.1fs" % (float(cad["max_gap"]) / sp)
        if len(gw) == 2:
            cadline += " over clip-window [%.1f-%.1f]" % (gw[0] / sp, gw[1] / sp)

    grade = loadjson(a.grade)
    gradeline = ""
    if grade:
        sig = grade.get("signals") or {}
        gradeline = "proxy grade %s/%s; hard_caps=%s; signals=%s" % (
            grade.get("grade"), grade.get("tier"),
            ",".join(grade.get("hard_caps") or []) or "none",
            json.dumps({k: sig.get(k) for k in
                        ("longest_static_gap", "max_residual_silence",
                         "terminal_loop_score", "first_payoff_offset")}))

    framemap = " ".join("#%d=%.1fs" % (f["k"], f["t"]) for f in frames)
    music_ok = a.mode != "curative"
    # the displayed music_down range MUST track the validator in parse_reply.py
    # (0.03 <= v <= current_vol - 0.01), else valid proposals get silently surfaced.
    try:
        vol_hi = max(0.03, round(float(a.vol) - 0.01, 2))
    except Exception:
        vol_hi = 0.14

    print(f"""You are the DIRECTOR doing a final quality pass on a finished 9:16 YouTube Short before it ships. Your job: WATCH the whole clip, judge it like a strict editor, and either pass it or call out exactly what is broken and which fixes to apply.

You are given a contact sheet — ONE image, a 4-column row-major grid of frames sampled across the whole {dur:.1f}s clip. READ IT WITH YOUR READ TOOL:
  {a.sheet}
Each cell is labelled with its timestamp. Frame index -> time: {framemap}
The burned captions, b-roll cutaways, speaker framing, title card and end card are all VISIBLE in the frames — judge what you actually see.

TITLE (the promise the clip must keep): {title or "(none)"}
MUSIC MOOD bed: {mood or "(none)"}   (current bed volume {a.vol})
DURATION: {dur:.1f}s

SPOKEN SCRIPT (phrase timings approx in CLIP time):
{script}

CAMERA FRAMING per shot (face = speaker hero-framed, listener = reaction shot, person = framed human with no detectable face, saliency = no-face/no-person crop): {shotline or "(none)"}
B-ROLL cutaways inserted (window -> search that sourced the footage):
{brolline or "(none)"}
CADENCE: {cadline or "(unknown)"}
{gradeline}

Review the WHOLE clip for anything a sharp editor would fix — anywhere, not just the open:
- COLD OPEN (0-2s swipe gate): is frame 1 the speaker's face, or buried behind b-roll / a blocking title card / a mis-crop? Does the first spoken sentence stand alone for a stranger?
- DEAD / RAMBLING TAIL: does the clip keep going after the payoff has landed — trailing filler, dead air, a static held frame, an unfinished thought? The clip should END right after the payoff word.
- B-ROLL FIT: is any cutaway tonally wrong or literal-but-wrong for what's being said (a cat laser toy for a tense "red dot", stock that fights the mood)?
- WRONG-PERSON FRAMING: is a punch-in hero-framing a silent LISTENER instead of the person talking?
- CAPTION TIMING: are burned captions out of sync, overlapping, cut off, or showing the wrong words?
- MUSIC BALANCE: does the bed drown the speech?
- HOOK: is the opening flat / pure throat-clearing with no curiosity gap?

You may ONLY apply fixes from this SUPPORTED set — pick the op for each issue:
- "tail_trim" {{"t1": <sec>}}  — the clip rambles/dies after the payoff. t1 = the CLIP-time second to cut to, just past the payoff word. Must be < {dur:.1f} and leave the clip >= {a.mindur:.0f}s. PIXEL-SAFE, always allowed.
- "music_down" {{"volume": <0.03-{vol_hi:.2f}>}} — the bed competes with speech; propose a lower bed volume (current {a.vol}). {"ALLOWED." if music_ok else "NOT available on this clip — use \"surface\" instead."}
- "surface" {{}} — ANY other issue (bad b-roll, wrong-person punch, cold-open defect, mistimed caption, flat hook). This applies NO automatic fix; it records a precise note for a human / a pipeline re-run. Always set "where".

Be conservative: only flag real, visible problems. A clean short returns verdict "ship" with an empty issues list. Do NOT invent issues to look thorough.

Reply with ONLY one JSON object, no prose, no code fences:
{{"verdict":"ship|revise","summary":"<one line>","issues":[{{"kind":"tail_dead|cold_open|broll_wrong|wrong_person|caption_mistime|music_loud|flat_hook|other","severity":"high|med|low","where":[<t0>,<t1>],"detail":"<what and why>","op":"tail_trim|music_down|surface","params":{{}}}}]}}""")


if __name__ == "__main__":
    main()
