import sys, os, json, subprocess, tempfile, argparse
import cv2, numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "face_landmarker.task")
POSE_MODEL = os.path.join(HERE, "models", "pose_landmarker.task")

# pose landmark indices (33-point BlazePose): nose, eyes, shoulders
NOSE, L_EYE, R_EYE, L_SH, R_SH = 0, 2, 5, 11, 12

# inner-lip + face-extent landmark indices (468/478 mesh)
UP, LO, TOP, CHIN = 13, 14, 10, 152
# stable, well-spread indices used to build a scale/position-invariant identity
# signature (face shape) so the same person can be matched across shots.
SIG = [33, 133, 362, 263, 1, 4, 168, 61, 291, 199, 152, 10, 234, 454, 70, 300]
SPEAK_VAR = 4e-4   # lip-openness variance above this == actively talking


def probe(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration", "-of", "json", path])
    j = json.loads(out)
    s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 24.0
    return int(s["width"]), int(s["height"]), fps, float(j["format"]["duration"])


def scenes(path, dur, thresh):
    # scene-change timestamps via ffmpeg select on a downscaled decode (cheap)
    p = subprocess.run([
        "ffmpeg", "-hide_banner", "-i", path,
        "-vf", "scale=480:-2,select='gt(scene,%g)',showinfo" % thresh,
        "-an", "-f", "null", "-"],
        stderr=subprocess.PIPE, text=True)
    cuts = []
    for line in p.stderr.splitlines():
        if "pts_time:" in line and "showinfo" in line:
            t = line.split("pts_time:")[1].split()[0]
            try:
                cuts.append(float(t))
            except ValueError:
                pass
    cuts = [c for c in cuts if 0.3 < c < dur - 0.1]
    bounds = [0.0] + cuts + [dur]
    shots = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a > 0.1:
            shots.append((a, b))
    return shots or [(0.0, dur)]


def frame(path, t, td, idx):
    fp = os.path.join(td, "s%d.png" % idx)
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-ss", "%.3f" % t,
        "-i", path, "-frames:v", "1", "-vf", "scale=1280:-2", fp],
        check=True)
    return cv2.imread(fp)


def faces(fl, img):
    res = fl.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    out = []
    for lm in res.face_landmarks:
        xs = [p.x for p in lm]
        ys = [p.y for p in lm]
        x0, y0 = min(xs), min(ys)
        fw = (max(xs) - x0) or 1e-6
        fh = abs(lm[CHIN].y - lm[TOP].y) or 1e-6
        # identity signature: each SIG landmark's position within the face bbox,
        # invariant to where/how big the face is in frame.
        sig = []
        for j in SIG:
            sig.append((lm[j].x - x0) / fw)
            sig.append((lm[j].y - y0) / (max(ys) - y0 or 1e-6))
        out.append({
            "cx": (min(xs) + max(xs)) / 2, "cy": (min(ys) + max(ys)) / 2,
            "w": max(xs) - x0, "h": max(ys) - y0,
            "eye": lm[TOP].y + 0.42 * fh,       # ~eyeline, normalized
            "open": abs(lm[LO].y - lm[UP].y) / fh,
            "sig": np.array(sig),
        })
    return out


def track(samples):
    # greedy nearest-center linking across sampled frames -> per-face tracks
    tracks = []
    for det in samples:
        for f in det:
            best, bd = None, 0.08
            for tr in tracks:
                last = tr[-1]
                d = ((last["cx"] - f["cx"]) ** 2 + (last["cy"] - f["cy"]) ** 2) ** 0.5
                if d < bd:
                    best, bd = tr, d
            if best is None:
                tracks.append([f])
            else:
                best.append(f)
    return tracks


def med(tr, k):
    return float(np.median([f[k] for f in tr]))


def trackvar(tr):
    return float(np.var([f["open"] for f in tr])) if len(tr) > 1 else 0.0


def trsig(tr):
    return np.median(np.stack([f["sig"] for f in tr]), axis=0)


def pick(tracks, dom=None):
    # speaker = most lip-activity (variance of openness). If a dominant-identity
    # signature is known (the clip's main storyteller), prefer the track that
    # matches it AND is talking, so we don't lock onto a secondary speaker.
    scored = [(trackvar(tr), tr) for tr in tracks]
    var_max = max(v for v, _ in scored)
    if dom is not None:
        near = [(v, tr) for v, tr in scored
                if float(np.linalg.norm(trsig(tr) - dom)) < SIG_THRESH]
        talking = [(v, tr) for v, tr in near if v >= SPEAK_VAR]
        if talking:
            return max(talking, key=lambda s: s[0])[1]
        if near and var_max < SPEAK_VAR:   # nobody clearly talking -> stay on main
            return max(near, key=lambda s: med(s[1], "h"))[1]
    if var_max < 1e-5:                     # no measurable lip motion -> central+big
        return max(tracks, key=lambda tr: med(tr, "h") - abs(med(tr, "cx") - 0.5))
    return max(scored, key=lambda s: s[0])[1]


def rep(tr):
    r = {k: float(np.median([f[k] for f in tr])) for k in ("cx", "cy", "w", "h", "eye")}
    r["sig"] = trsig(tr)
    r["var"] = trackvar(tr)
    return r


SIG_THRESH = 0.55   # euclidean distance under which two face signatures are "same person"


def even(v):
    v = int(round(v))
    return v - (v & 1)


def facebox(face, sw, sh, tw, th, face_frac, max_zoom):
    ar = tw / th
    face_px = max(face["h"] * sh, 1.0)
    crop_h = face_px / face_frac
    crop_h = max(crop_h, th / max_zoom)         # upscale cap
    crop_h = min(crop_h, sh, sw / ar)           # fit source bounds
    crop_w = crop_h * ar
    eye_y = face["eye"] * sh
    top = eye_y - crop_h / 3.0                   # eyeline on upper third
    left = face["cx"] * sw - crop_w / 2.0
    top = max(0.0, min(top, sh - crop_h))
    left = max(0.0, min(left, sw - crop_w))
    return even(crop_w), even(crop_h), even(left), even(top)


def saliency(imgs, sw, sh, tw, th):
    ar = tw / th
    sal = cv2.saliency.StaticSaliencyFineGrained_create()
    acc = None
    for img in imgs:
        ok, m = sal.computeSaliency(img)
        if not ok:
            continue
        acc = m if acc is None else acc + m
    crop_h = min(sh, sw / ar)                    # cover only, no upscale
    crop_w = crop_h * ar
    if acc is None:
        cx = sw / 2.0
    else:
        col = acc.sum(axis=0)
        cx = (np.arange(len(col)) * col).sum() / (col.sum() or 1)
        cx *= sw / acc.shape[1]
    left = max(0.0, min(cx - crop_w / 2.0, sw - crop_w))
    return even(crop_w), even(crop_h), even(left), even((sh - crop_h) / 2)


def poselm():
    return vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=POSE_MODEL),
        running_mode=vision.RunningMode.IMAGE, num_poses=1))


def person(pl, img):
    # one prominent person -> normalized {cx, head, top, bot}, or None. Used to
    # frame a faceless-but-human shot (FaceLandmarker missed it: small / profile
    # / back-of-head) on the person instead of falling to contrast-saliency.
    res = pl.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    if not res.pose_landmarks:
        return None
    lm = res.pose_landmarks[0]
    vis = [p for p in lm if getattr(p, "visibility", 1.0) >= 0.5]
    if len(vis) < 6:
        return None
    xs = [p.x for p in vis]
    ys = [p.y for p in vis]
    top, bot = min(ys), max(ys)
    if bot - top < 0.12:                         # too small to be a framing subject
        return None

    def seen(i):
        return getattr(lm[i], "visibility", 1.0) >= 0.3
    head = (lm[L_EYE].y + lm[R_EYE].y) / 2 if (seen(L_EYE) and seen(R_EYE)) else lm[NOSE].y
    cx = (lm[L_SH].x + lm[R_SH].x) / 2 if (seen(L_SH) and seen(R_SH)) else (min(xs) + max(xs)) / 2
    return {"cx": cx, "head": head, "top": top, "bot": bot}


def personbox(p, sw, sh, tw, th, max_zoom, person_frac=0.62):
    # same geometry as facebox() but sized from the person's vertical extent and
    # anchored on the head, so the subject reads big with the head on the upper third.
    ar = tw / th
    subj_px = max((p["bot"] - p["top"]) * sh, 1.0)
    crop_h = subj_px / person_frac
    crop_h = max(crop_h, th / max_zoom)          # upscale cap
    crop_h = min(crop_h, sh, sw / ar)            # fit source bounds
    crop_w = crop_h * ar
    head_y = p["head"] * sh
    top = head_y - crop_h / 3.0                  # head/eyeline on the upper third
    left = p["cx"] * sw - crop_w / 2.0
    top = max(0.0, min(top, sh - crop_h))
    left = max(0.0, min(left, sw - crop_w))
    return even(crop_w), even(crop_h), even(left), even(top)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("out")
    ap.add_argument("--target", default="1080x1920")
    ap.add_argument("--face_frac", type=float, default=0.45)
    ap.add_argument("--max_zoom", type=float, default=2.0)
    ap.add_argument("--scene_thresh", type=float, default=0.4)
    ap.add_argument("--samples", type=int, default=7)
    a = ap.parse_args()

    tw, th = (int(x) for x in a.target.split("x"))
    sw, sh, fps, dur = probe(a.input)
    shots = scenes(a.input, dur, a.scene_thresh)

    fl = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=MODEL),
        running_mode=vision.RunningMode.IMAGE, num_faces=5))

    # PASS 1: sample + detect + track every shot (keep frames for pass 2).
    td = tempfile.mkdtemp()
    shotdata = []
    for si, (a0, a1) in enumerate(shots):
        n = max(2, a.samples if (a1 - a0) > 0.5 else 2)
        ts = [a0 + (a1 - a0) * (i + 0.5) / n for i in range(n)]
        imgs, dets = [], []
        for i, t in enumerate(ts):
            img = frame(a.input, min(t, dur - 0.05), td, si * 100 + i)
            if img is None:
                continue
            imgs.append(img)
            dets.append(faces(fl, img))
        shotdata.append((a0, a1, track(dets), imgs))

    # identify the dominant speaker: cluster every track's face signature across
    # all shots, weighted by shot duration; the longest-present identity is the
    # storyteller. Used to avoid hero-framing secondary speakers / listeners.
    clusters = []
    for a0, a1, tracks, _ in shotdata:
        for tr in tracks:
            s = trsig(tr)
            best, bd = None, SIG_THRESH
            for c in clusters:
                d = float(np.linalg.norm(s - c["sig"]))
                if d < bd:
                    best, bd = c, d
            if best is None:
                clusters.append({"sig": s.copy(), "sigs": [s], "dur": a1 - a0})
            else:
                best["sigs"].append(s)
                best["dur"] += a1 - a0
                best["sig"] = np.mean(np.stack(best["sigs"]), axis=0)
    dom = max(clusters, key=lambda c: c["dur"])["sig"] if clusters else None
    multi = len(clusters) >= 2   # only de-emphasize "others" when >1 identity exists

    # PASS 2: per shot, pick the speaker (dominant-biased) and frame it. A
    # non-dominant face that isn't talking is a listener reaction shot -> frame
    # it looser so the short doesn't dwell hero-framed on the wrong person.
    boxes = []
    pl = None
    for si, (a0, a1, tracks, imgs) in enumerate(shotdata):
        if tracks:
            tr = pick(tracks, dom)
            r = rep(tr)
            listener = multi and r["var"] < SPEAK_VAR and \
                float(np.linalg.norm(r["sig"] - dom)) >= SIG_THRESH
            ff = a.face_frac * 0.66 if listener else a.face_frac
            box = facebox(r, sw, sh, tw, th, ff, a.max_zoom)
            kind = "listener" if listener else "face"
        else:
            # no face -> try a person (pose) before falling to contrast-saliency,
            # so action / establishing shots frame the human, not bright scenery.
            ppl = None
            if imgs:
                if pl is None:
                    pl = poselm()
                cand = [c for c in (person(pl, im) for im in imgs) if c]
                if len(cand) >= max(1, (len(imgs) + 2) // 3):   # majority-ish, reject flukes
                    ppl = {k: float(np.median([c[k] for c in cand]))
                           for k in ("cx", "head", "top", "bot")}
            if ppl:
                box = personbox(ppl, sw, sh, tw, th, a.max_zoom)
                kind = "person"
            elif imgs:
                box = saliency(imgs, sw, sh, tw, th)
                kind = "saliency"
            else:
                box = (even(min(sh, sw * tw / th)), even(min(sh, sw / (tw / th))),
                       even((sw - min(sh, sw * tw / th)) / 2), 0)
                kind = "saliency"
        cw, ch, cx, cy = box
        boxes.append({"t0": a0, "t1": a1, "kind": kind,
                      "crop": [cw, ch, cx, cy]})
        print("shot %d [%.2f-%.2f] %s crop=%dx%d@%d,%d" %
              (si, a0, a1, kind, cw, ch, cx, cy), file=sys.stderr)

    plan = os.path.splitext(a.out)[0] + ".fillplan.json"
    with open(plan, "w") as f:
        json.dump({"src": [sw, sh], "target": [tw, th], "shots": boxes}, f)
    print(plan)


if __name__ == "__main__":
    main()
