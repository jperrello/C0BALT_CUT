import sys, os, re, json, math, struct, subprocess, tempfile, argparse

VERSION = 1
HERE = os.path.dirname(os.path.abspath(__file__))
FILLMODEL = os.path.join(HERE, "..", "fill-vertical", "models", "face_landmarker.task")

SCENE = float(os.environ.get("PROFILE_SCENE", "0.3"))
SAMPLES = int(os.environ.get("PROFILE_SAMPLES", "16"))
SILENCE_DB = os.environ.get("PROFILE_SILENCE_DB", "-30dB")
MUSIC_DB = float(os.environ.get("PROFILE_MUSIC_DB", "-48"))
CAPTION_EDGE = float(os.environ.get("PROFILE_CAPTION_EDGE", "0.035"))


def run(cmd, **kw):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kw)


def probe(path):
    p = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-show_entries", "format=duration",
             "-of", "json", path])
    j = json.loads(p.stdout or "{}")
    s = (j.get("streams") or [{}])[0]
    dur = (j.get("format") or {}).get("duration") or 0
    return int(s.get("width") or 0), int(s.get("height") or 0), float(dur or 0)


def scenes(path, dur):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
             "-vf", "select='gt(scene,%g)',showinfo" % SCENE, "-an", "-f", "null", "-"])
    ts = []
    for m in re.finditer(r"pts_time:([0-9.]+)", p.stderr):
        t = float(m.group(1))
        if 0.0 <= t <= dur:
            ts.append(round(t, 3))
    return sorted(set(ts))


def cuts(changes, dur):
    if dur <= 0:
        return {}
    bounds = [0.0] + changes + [dur]
    shots = sorted(y - x for x, y in zip(bounds, bounds[1:]) if y > x)
    if not shots:
        return {}
    med = shots[len(shots) // 2]
    p90 = shots[min(len(shots) - 1, int(len(shots) * 0.9))]
    return {
        "cuts_per_min": round(len(changes) / dur * 60.0, 1),
        "median_shot_sec": round(med, 2),
        "p90_shot_sec": round(p90, 2),
        "longest_static_gap": round(max(shots), 2),
    }


def silences(path):
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path,
             "-af", "silencedetect=noise=%s:d=0.3" % SILENCE_DB, "-f", "null", "-"])
    spans = []
    start = None
    for line in p.stderr.splitlines():
        m = re.search(r"silence_start:\s*([0-9.]+)", line)
        if m:
            start = float(m.group(1))
            continue
        m = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m and start is not None:
            spans.append((start, float(m.group(1))))
            start = None
    return spans


def pcm(path):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "8000",
                        "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw = p.stdout or b""
    n = len(raw) // 2
    return struct.unpack("<%dh" % n, raw[:n * 2]) if n else ()


def rmswin(samples, sr=8000, win=0.05):
    step = int(sr * win)
    out = []
    for i in range(0, len(samples) - step, step):
        acc = 0
        for v in samples[i:i + step]:
            acc += v * v
        out.append(math.sqrt(acc / step) / 32768.0)
    return out


def db(x):
    if x <= 0:
        return -96.0
    return 20.0 * math.log10(x)


def audio(path, dur, sil):
    samples = pcm(path)
    if not samples or dur <= 0:
        return {}, []
    wins = rmswin(samples)
    if not wins:
        return {}, []
    quiet = sorted(wins)[:max(1, len(wins) // 20)]
    floor = db(sum(quiet) / len(quiet))
    # onsets: RMS jump > 4x the previous window and above the median level
    med = sorted(wins)[len(wins) // 2]
    onsets = 0
    for a, b in zip(wins, wins[1:]):
        if b > max(4.0 * a, 2.0 * med, 0.02):
            onsets += 1
    silent = sum(e - s for s, e in sil)
    return {
        "onsets_per_min": round(onsets / dur * 60.0, 1),
        "music_floor_db": round(floor, 1),
        "music_present": floor > MUSIC_DB,
    }, [round(1.0 - silent / dur, 3)]


def grabs(path, dur, td, n):
    ts = [round(i / max(1, n - 1) * max(0.0, dur - 0.12), 3) for i in range(n)]
    out = []
    for i, t in enumerate(ts):
        fp = os.path.join(td, "p%02d.png" % i)
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.3f" % t,
             "-i", path, "-frames:v", "1", fp])
        if os.path.isfile(fp):
            out.append((t, fp))
    return out


def landmarker():
    if not os.path.isfile(FILLMODEL):
        return None
    try:
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        return vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=FILLMODEL),
            running_mode=vision.RunningMode.IMAGE, num_faces=3))
    except Exception:
        return None


def face(fl, fp):
    try:
        import cv2
        import mediapipe as mp
        img = cv2.imread(fp)
        if img is None:
            return None
        res = fl.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                                 data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    except Exception:
        return None
    for lm in res.face_landmarks:
        xs = [p.x for p in lm]
        ys = [p.y for p in lm]
        if (max(xs) - min(xs)) * (max(ys) - min(ys)) >= 0.015:
            return True
    return False


def edges(fp, y0, y1):
    try:
        import cv2
        img = cv2.imread(fp)
        if img is None:
            return None
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h = g.shape[0]
        band = g[int(h * y0):int(h * y1), :]
        e = cv2.Canny(band, 80, 200)
        return float((e > 0).mean())
    except Exception:
        return None


def visual(frames, fl):
    faces = []
    caps = []
    for t, fp in frames:
        faces.append((t, face(fl, fp) if fl else None))
        caps.append((t, edges(fp, 0.55, 0.82)))
    known = [(t, v) for t, v in faces if v is not None]
    out = {"visual": {}, "captions": {}, "needs": []}
    if known:
        frac = sum(1 for _, v in known if v) / len(known)
        out["visual"]["face_fraction"] = round(frac, 3)
        out["visual"]["cutaway_fraction"] = round(1.0 - frac, 3)
        runs = 0
        prev = True
        for _, v in known:
            if not v and prev:
                runs += 1
            prev = v
        out["visual"]["cutaway_count"] = runs
        f0 = known[0][1] if known[0][0] < 1.0 else None
        if f0 is None:
            out["needs"].append("opens_on_face")
        else:
            out["visual"]["opens_on_face"] = bool(f0)
    else:
        out["needs"] += ["opens_on_face", "cutaway_fraction"]
    dens = [(t, d) for t, d in caps if d is not None]
    if dens:
        out["captions"]["present_fraction"] = round(
            sum(1 for _, d in dens if d > CAPTION_EDGE) / len(dens), 3)
        out["captions"]["band"] = "lower_third"
    return out


def titleopen(path, td):
    fp = os.path.join(td, "title.png")
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.6", "-i", path,
         "-frames:v", "1", fp])
    d = edges(fp, 0.02, 0.22) if os.path.isfile(fp) else None
    if d is None:
        return None
    return d > 0.04


def transcribe(path, td):
    tx = os.environ.get("PROFILE_TRANSCRIPT", "")
    if tx and os.path.isfile(tx):
        try:
            return json.load(open(tx))
        except Exception:
            return None
    sh = os.path.join(HERE, "..", "transcribe", "transcribe.sh")
    out = os.path.join(td, "tx.json")
    if not os.path.isfile(sh):
        return None
    p = run(["bash", sh, path, out])
    if p.returncode != 0 or not os.path.isfile(out):
        return None
    try:
        return json.load(open(out))
    except Exception:
        return None


def speech(tx, dur, sil):
    out = {}
    longest = max((e - s for s, e in sil), default=0.0)
    out["max_silence_sec"] = round(longest, 2)
    if dur > 0:
        out["speech_fraction"] = round(1.0 - sum(e - s for s, e in sil) / dur, 3)
    if tx and dur > 0:
        words = tx.get("words") or []
        if words:
            out["words_per_min"] = round(len(words) / dur * 60.0, 1)
    return out


def build(path, skiptx):
    w, h, dur = probe(path)
    if dur <= 0:
        return {"style_profile_version": VERSION, "clip": path, "error": "unreadable"}
    td = tempfile.mkdtemp()
    changes = scenes(path, dur)
    sil = silences(path)
    aud, _ = audio(path, dur, sil)
    frames = grabs(path, dur, td, SAMPLES)
    vis = visual(frames, landmarker())
    tx = None if skiptx else transcribe(path, td)
    needs = list(vis["needs"]) + ["broll_mode", "caption_style", "production_class", "hook_device"]

    doc = {
        "style_profile_version": VERSION,
        "clip": os.path.abspath(path),
        "duration_sec": round(dur, 2),
        "cuts": cuts(changes, dur),
        "speech": speech(tx, dur, sil),
        "visual": vis["visual"],
        "captions": vis["captions"],
        "audio": aud,
        "hook": {
            "first_cut_sec": round(changes[0], 2) if changes else None,
            "title_overlay_open": titleopen(path, td),
        },
        "vision": {},
        "meta": {"width": w, "height": h, "needs_vision": needs, "notes": []},
    }
    try:
        import shutil
        shutil.rmtree(td, ignore_errors=True)
    except Exception:
        pass
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("out")
    ap.add_argument("--skip-transcribe", action="store_true")
    a = ap.parse_args()
    try:
        doc = build(a.clip, a.skip_transcribe)
    except Exception as e:
        doc = {"style_profile_version": VERSION, "clip": a.clip, "error": str(e)[:200]}
    json.dump(doc, open(a.out, "w"), indent=2)
    print(json.dumps({"out": a.out, "needs_vision": (doc.get("meta") or {}).get("needs_vision", []),
                      "error": doc.get("error")}))


if __name__ == "__main__":
    main()
