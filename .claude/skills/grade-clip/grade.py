import sys, os, re, json, glob, subprocess, tempfile, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
FILLMODEL = os.path.join(HERE, "..", "fill-vertical", "models", "face_landmarker.task")

# proxy thresholds (env-overridable)
MIN_UPLOAD = float(os.environ.get("GRADE_MIN_UPLOAD", "60"))
OPEN_GUARD = float(os.environ.get("GRADE_OPEN_GUARD_SEC", "2.2"))
FIRST_CHANGE_BUDGET = float(os.environ.get("GRADE_FIRST_CHANGE_SEC", "3.0"))
PAYOFF_BUDGET = float(os.environ.get("GRADE_PAYOFF_SEC", "3.0"))
STATIC_BUDGET = float(os.environ.get("GRADE_STATIC_GAP_SEC", "5.0"))
SILENCE_BUDGET = float(os.environ.get("GRADE_SILENCE_SEC", "0.8"))
MIN_CAPTION_WORDS = int(os.environ.get("GRADE_MIN_CAPTION_WORDS", "3"))
SILENCE_DB = os.environ.get("GRADE_SILENCE_DB", "-30dB")

STOP = set("the a an and or of to in on for with is are was were be been being this that "
           "it he she they you i we him her them his my your our their so but if then "
           "as at by from up out about into over after before just like get got".split())


def run(cmd, **kw):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)


def probe(path):
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,duration",
             "-show_entries", "format=duration", "-of", "json", path])
    j = json.loads(p.stdout or "{}")
    s = (j.get("streams") or [{}])[0]
    w = int(s.get("width") or 0)
    h = int(s.get("height") or 0)
    dur = s.get("duration") or (j.get("format") or {}).get("duration") or 0
    return w, h, float(dur or 0)


def loadjson(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        return json.load(open(path))
    except Exception:
        return None


# ---- sidecar discovery -----------------------------------------------------
# in-chain clips live at work/<id>/clip_NN.final.mp4 with siblings clip_NN.*.
# finished output clips have a title stem and usually NO co-located sidecars.
def sidecars(clip):
    d = os.path.dirname(os.path.abspath(clip))
    base = os.path.basename(clip)
    m = re.match(r"(clip_\d+)\.", base)
    stem = os.path.join(d, m.group(1)) if m else os.path.splitext(os.path.abspath(clip))[0]

    def first(*cands):
        for c in cands:
            if c and os.path.isfile(c):
                return c
        return None

    return {
        "fill": first(stem + ".vert.fillplan.json", stem + ".fillplan.json",
                      os.path.splitext(clip)[0] + ".fillplan.json"),
        "cadence": first(os.path.splitext(clip)[0] + ".cadence.json",
                         stem + ".cadence.json"),
        "chunks": first(stem + ".chunks.json",
                        os.path.splitext(clip)[0] + ".chunks.json"),
        "broll": first(stem + ".broll_plan.json",
                       os.path.splitext(clip)[0] + ".broll_plan.json"),
        "title": first(stem + ".title.txt", os.path.splitext(clip)[0] + ".title.txt"),
        "transcript": first(stem + ".tight.transcript.json", stem + ".transcript.json",
                            os.path.splitext(clip)[0] + ".transcript.json"),
        "verify": first(stem + ".verify.json", os.path.splitext(clip)[0] + ".verify.json"),
    }


# ---- pixel signals ---------------------------------------------------------
def grabframe(path, t, td, name):
    fp = os.path.join(td, name)
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.3f" % max(0.0, t),
         "-i", path, "-frames:v", "1", fp])
    if not os.path.isfile(fp):
        return None
    try:
        import cv2
        return cv2.imread(fp)
    except Exception:
        return None


def faceframe(img):
    # TRUE when a real face occupies a meaningful area of frame 0
    if img is None:
        return None
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except Exception:
        return None
    if not os.path.isfile(FILLMODEL):
        return None
    try:
        fl = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=FILLMODEL),
            running_mode=vision.RunningMode.IMAGE, num_faces=3))
        res = fl.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                                 data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    except Exception:
        return None
    for lm in res.face_landmarks:
        xs = [p.x for p in lm]
        ys = [p.y for p in lm]
        area = (max(xs) - min(xs)) * (max(ys) - min(ys))
        if area >= 0.02:                 # face spans >~2% of frame area -> real
            return True
    return False


def letterbox(img):
    # near-constant edge bands (black bars / blurred pillarbox) -> letterbox.
    # full-bleed punch-in has high variance everywhere.
    if img is None:
        return False
    try:
        import cv2, numpy as np
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype("float32")
    except Exception:
        return False
    h, w = g.shape
    bh = max(2, int(h * 0.06))
    bw = max(2, int(w * 0.06))
    top, bot = g[:bh, :], g[h - bh:, :]
    left, right = g[:, :bw], g[:, w - bw:]
    core = float(g.std())
    if core < 1.0:
        return False                     # whole frame flat -> not a bar artifact

    # A real bar is near-constant AND dark. A single dark edge band is just dark
    # scenery (e.g. a podcast backdrop under the cold-open title banner) -> NOT a
    # bar. Letterbox/pillarbox always comes as an OPPOSING PAIR (top+bottom or
    # left+right), so require both members of a pair to qualify.
    def bar(b):
        return float(b.std()) < 6.0 and float(b.mean()) < 32.0
    return (bar(top) and bar(bot)) or (bar(left) and bar(right))


def creditopen(path, td):
    # text/edge density in the top ~12% banner at t~0.6s -> credit lit at open
    # (the source credit must appear only in the final CREDIT_TAIL). Approximate.
    img = grabframe(path, 0.6, td, "credit.png")
    if img is None:
        return False
    try:
        import cv2, numpy as np
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    except Exception:
        return False
    h, w = g.shape
    band = g[:max(2, int(h * 0.12)), :]
    edges = cv2.Canny(band, 80, 200)
    return float((edges > 0).mean()) > 0.045


def silence(path):
    # longest residual silence (sec) via ffmpeg silencedetect
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
             "-af", "silencedetect=noise=%s:d=0.3" % SILENCE_DB, "-f", "null", "-"])
    longest = 0.0
    for m in re.finditer(r"silence_duration:\s*([0-9.]+)", p.stderr):
        longest = max(longest, float(m.group(1)))
    return round(longest, 2)


def loopscore(path, dur, td):
    # frame0 <-> last-frame similarity (normalized hist correlation) -> 0-1
    a = grabframe(path, 0.0, td, "loop0.png")
    b = grabframe(path, max(0.0, dur - 0.12), td, "loop1.png")
    if a is None or b is None:
        return None
    try:
        import cv2, numpy as np
        ga = cv2.cvtColor(cv2.resize(a, (64, 114)), cv2.COLOR_BGR2GRAY)
        gb = cv2.cvtColor(cv2.resize(b, (64, 114)), cv2.COLOR_BGR2GRAY)
        ha = cv2.calcHist([ga], [0], None, [64], [0, 256])
        hb = cv2.calcHist([gb], [0], None, [64], [0, 256])
        cv2.normalize(ha, ha)
        cv2.normalize(hb, hb)
        c = float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL))
    except Exception:
        return None
    return round(max(0.0, min(1.0, (c + 1.0) / 2.0)), 3)


def deadtail(path, dur, td, maxsil):
    # trailing silence in last ~1.5s AND/OR static final ~1s (low frame delta)
    trailing = maxsil >= 1.0
    a = grabframe(path, max(0.0, dur - 1.0), td, "tail0.png")
    b = grabframe(path, max(0.0, dur - 0.1), td, "tail1.png")
    static = False
    if a is not None and b is not None:
        try:
            import cv2, numpy as np
            ga = cv2.cvtColor(cv2.resize(a, (96, 170)), cv2.COLOR_BGR2GRAY).astype("float32")
            gb = cv2.cvtColor(cv2.resize(b, (96, 170)), cv2.COLOR_BGR2GRAY).astype("float32")
            static = float(np.abs(ga - gb).mean()) < 1.5
        except Exception:
            static = False
    # silencedetect reports the silence regardless of where; pair it with a
    # static tail so a mid-clip pause doesn't false-trip dead_tail.
    return bool(trailing and static), {"trailing_silence": trailing, "static_tail": static}


def scenechanges(path, dur, scene):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
             "-vf", "select='gt(scene,%g)',showinfo" % scene, "-an", "-f", "null", "-"])
    ts = []
    for line in p.stderr.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            if 0.0 <= t <= dur:
                ts.append(round(t, 3))
    return sorted(set(ts))


def staticgap(changes, dur):
    bounds = [0.0] + changes + [dur]
    gap = 0.0
    for x, y in zip(bounds, bounds[1:]):
        gap = max(gap, y - x)
    return round(gap, 2)


# ---- plan-derived signals --------------------------------------------------
def firstvisualchange(sc):
    cands = []
    broll = loadjson(sc["broll"])
    if broll:
        for p in broll.get("picks", []):
            if "t0" in p:
                cands.append(float(p["t0"]))
    chunks = loadjson(sc["chunks"])
    if chunks:
        cs = chunks.get("chunks", [])
        if cs:
            # first caption swap is the end of chunk0
            cands.append(float(cs[0].get("t1", 0.0)))
    if not cands:
        return None
    cands = [c for c in cands if c > 0.0]
    return round(min(cands), 2) if cands else None


def openingcaptionwords(sc):
    chunks = loadjson(sc["chunks"])
    if not chunks:
        return None
    cs = chunks.get("chunks", [])
    if not cs:
        return None
    c0 = cs[0]
    if float(c0.get("t0", 0.0)) > OPEN_GUARD + 1.0:
        return 0                         # nothing in the swipe window
    words = c0.get("words")
    if isinstance(words, list):
        return len(words)
    return len(str(c0.get("text", "")).split())


def payoffoffset(sc):
    title = sc["title"]
    chunks = loadjson(sc["chunks"])
    if not title or not chunks or not os.path.isfile(title):
        return None
    cs = chunks.get("chunks", [])
    if not cs:
        return None
    keys = set()
    for w in re.findall(r"[a-z']+", open(title).read().lower()):
        if len(w) >= 4 and w not in STOP:
            keys.add(w)
    if not keys:
        return None
    best = None
    bestscore = 0
    for c in cs:
        toks = set(re.findall(r"[a-z']+", str(c.get("text", "")).lower()))
        score = len(keys & toks)
        if score > bestscore:
            bestscore, best = score, c
    if best is None:
        return None
    return round(float(best.get("t0", 0.0)), 2)


# ---- grade formula ---------------------------------------------------------
def grade(signals, hard, claude):
    # start near 99 and subtract documented penalties for SOFT signals, then
    # apply the Claude rubric, THEN clamp to <=40 on any hard cap.
    g = 99.0
    notes = []

    gap = signals.get("longest_static_gap")
    if gap is not None and gap > STATIC_BUDGET:
        pen = min(20.0, (gap - STATIC_BUDGET) * 4.0)
        g -= pen; notes.append("static_gap-%.0f" % pen)

    po = signals.get("first_payoff_offset")
    if po is None:
        g -= 6.0; notes.append("payoff_unknown-6")
    elif po > PAYOFF_BUDGET:
        pen = min(14.0, (po - PAYOFF_BUDGET) * 3.0)
        g -= pen; notes.append("late_payoff-%.0f" % pen)

    sil = signals.get("max_residual_silence")
    if sil is not None and sil > SILENCE_BUDGET:
        pen = min(12.0, (sil - SILENCE_BUDGET) * 8.0)
        g -= pen; notes.append("silence-%.0f" % pen)

    loop = signals.get("terminal_loop_score")
    if loop is not None:
        pen = (1.0 - loop) * 8.0
        g -= pen; notes.append("loop-%.0f" % pen)

    cw = signals.get("opening_caption_words")
    if cw is not None and cw < MIN_CAPTION_WORDS:
        g -= 6.0; notes.append("thin_caption-6")

    fc = signals.get("first_visual_change_sec")
    if fc is None or fc > FIRST_CHANGE_BUDGET:
        g -= 5.0; notes.append("late_change-5")

    if claude:
        # rubric 0-10 each; pull the grade toward the mean of the three terms
        vals = [claude.get(k) for k in ("hook_payoff", "open_loop", "cold_context")]
        vals = [float(v) for v in vals if isinstance(v, (int, float))]
        if vals:
            mean = sum(vals) / len(vals)
            pen = (10.0 - mean) * 2.4
            g -= pen; notes.append("claude-%.0f" % pen)

    g = max(0.0, min(99.0, g))
    if hard:
        g = min(g, 40.0)
    return int(round(g)), notes


CAP_ROUTE = {
    "letterbox": "rerun_recommended",
    "face_withheld": "shot0_repunch",
    "credit_at_open": "credit_rerender",
    "blocking_card": "card_rerender",
    "dead_tail": None,
}


def routes(hard, signals, sc):
    r = []
    broll = loadjson(sc["broll"])
    if broll:
        for p in broll.get("picks", []):
            if float(p.get("t0", 9e9)) <= OPEN_GUARD and float(p.get("t1", 0)) > 0:
                r.append("broll_open_truncate")
                break
    for cap in hard:
        route = CAP_ROUTE.get(cap)
        if route and route not in r:
            r.append(route)
    return r


def source(clip):
    d = os.path.basename(os.path.dirname(os.path.abspath(clip)))
    if d and d not in (".", ""):
        return d
    return os.path.splitext(os.path.basename(clip))[0]


def gradeclip(clip, skipclaude, scene):
    sc = sidecars(clip)
    w, h, dur = probe(clip)
    if dur <= 0.0 or w <= 0 or h <= 0:
        # unreadable / non-video artifact -> not gradeable, not upload-ready
        return {"clip": clip, "grade": 0, "tier": "DROSS", "hard_caps": [],
                "signals": {}, "fix_routes": [], "source": source(clip),
                "error": "unreadable (duration/dims unavailable)"}
    td = tempfile.mkdtemp()

    f0 = grabframe(clip, 0.0, td, "f0.png")
    fill = loadjson(sc["fill"])
    shot0face = None
    shot0person = False
    if fill:
        shots = fill.get("shots") or []
        if shots:
            shot0face = (shots[0].get("kind") == "face")
            shot0person = (shots[0].get("kind") == "person")

    framefab = faceframe(f0)
    # frame1_is_face: true if pixel detect says face OR (no detect) fillplan shot0 is face
    if framefab is None:
        frame1face = shot0face if shot0face is not None else None
    else:
        frame1face = bool(framefab)

    # face_withheld hard-cap: no face in frame0 OR fillplan shot0 kind != face
    facewithheld = (framefab is False) or (shot0face is False)
    if framefab is None and shot0face is None:
        facewithheld = False             # no evidence either way -> don't cap
    if shot0person and framefab is not True:
        facewithheld = False             # deliberate human cold open (no face) -> soft, not a hard cap

    lb = letterbox(f0)
    credit = creditopen(clip, td)
    maxsil = silence(clip)
    loop = loopscore(clip, dur, td)
    dead, deadinfo = deadtail(clip, dur, td, maxsil)

    cadence = loadjson(sc["cadence"])
    if cadence and "max_gap" in cadence:
        gap = float(cadence["max_gap"])
    else:
        gap = staticgap(scenechanges(clip, dur, scene), dur) if dur > 0 else None

    fc = firstvisualchange(sc)
    if fc is None and dur > 0:
        ch = scenechanges(clip, dur, scene)
        ch = [c for c in ch if c > 0.05]
        fc = round(ch[0], 2) if ch else None

    signals = {
        "frame1_is_face": frame1face,
        "letterbox_bars": bool(lb),
        "credit_lit_at_open": bool(credit),
        "first_visual_change_sec": fc,
        "first_payoff_offset": payoffoffset(sc),
        "longest_static_gap": gap,
        "opening_caption_words": openingcaptionwords(sc),
        "max_residual_silence": maxsil,
        "terminal_loop_score": loop,
    }

    hard = []
    if lb:
        hard.append("letterbox")
    if facewithheld:
        hard.append("face_withheld")
    if credit:
        hard.append("credit_at_open")
    if dead:
        hard.append("dead_tail")

    claude = None
    if not skipclaude:
        claude = sc.get("_claude")       # injected by the .sh after the pane call
    if claude:
        signals["claude"] = claude

    g, _notes = grade(signals, hard, claude)
    fr = routes(hard, signals, sc)

    # tier logic
    if not hard and g >= MIN_UPLOAD:
        tier = "GOLD"
    elif hard and all(CAP_ROUTE.get(c) and CAP_ROUTE.get(c) != "rerun_recommended" for c in hard):
        tier = "FIXABLE"
    else:
        tier = "DROSS"

    rel = clip
    grade_doc = {
        "clip": rel,
        "grade": g,
        "tier": tier,
        "hard_caps": hard,
        "signals": signals,
        "fix_routes": fr,
        "source": source(clip),
    }
    grade_doc["_deadtail"] = deadinfo
    try:
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    except Exception:
        pass
    return grade_doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("out")
    ap.add_argument("--skip-claude", action="store_true")
    ap.add_argument("--scene", type=float, default=float(os.environ.get("GRADE_SCENE", "0.3")))
    ap.add_argument("--claude-json", default="")
    a = ap.parse_args()

    sc_claude = None
    if a.claude_json and os.path.isfile(a.claude_json):
        try:
            sc_claude = json.load(open(a.claude_json))
        except Exception:
            sc_claude = None

    try:
        doc = gradeclip(a.clip, a.skip_claude, a.scene)
    except Exception as e:
        # NON-FATAL: emit an empty DROSS verdict and exit 0
        doc = {"clip": a.clip, "grade": 0, "tier": "DROSS", "hard_caps": [],
               "signals": {}, "fix_routes": [], "source": source(a.clip),
               "error": str(e)[:200]}

    if sc_claude and not a.skip_claude:
        doc.setdefault("signals", {})["claude"] = sc_claude
        # re-grade including the rubric
        g, _ = grade(doc["signals"], doc.get("hard_caps", []), sc_claude)
        doc["grade"] = g
        if not doc.get("hard_caps") and g >= MIN_UPLOAD:
            doc["tier"] = "GOLD"

    doc.pop("_deadtail", None)
    with open(a.out, "w") as f:
        json.dump(doc, f, indent=2)
    print(json.dumps(doc))


if __name__ == "__main__":
    main()
