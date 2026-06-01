import sys, os, json, subprocess, tempfile, argparse
import cv2, numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(HERE, "models", "face_landmarker.task")

# inner-lip + face-extent landmark indices (468/478 mesh)
UP, LO, TOP, CHIN = 13, 14, 10, 152


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
        fh = abs(lm[CHIN].y - lm[TOP].y) or 1e-6
        out.append({
            "cx": (min(xs) + max(xs)) / 2, "cy": (min(ys) + max(ys)) / 2,
            "w": max(xs) - min(xs), "h": max(ys) - min(ys),
            "eye": lm[TOP].y + 0.42 * fh,       # ~eyeline, normalized
            "open": abs(lm[LO].y - lm[UP].y) / fh,
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


def pick(tracks):
    # speaker = most lip-activity (variance of openness); tie -> biggest+central
    def med(tr, k):
        return float(np.median([f[k] for f in tr]))
    scored = []
    for tr in tracks:
        var = float(np.var([f["open"] for f in tr])) if len(tr) > 1 else 0.0
        scored.append((var, tr))
    var_max = max(v for v, _ in scored)
    if var_max < 1e-5:                     # no measurable lip motion -> central+big
        def central(tr):
            return med(tr, "h") - abs(med(tr, "cx") - 0.5)
        return max(tracks, key=central)
    return max(scored, key=lambda s: s[0])[1]


def rep(tr):
    return {k: float(np.median([f[k] for f in tr])) for k in ("cx", "cy", "w", "h", "eye")}


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("out")
    ap.add_argument("--target", default="1080x1920")
    ap.add_argument("--face_frac", type=float, default=0.45)
    ap.add_argument("--max_zoom", type=float, default=2.0)
    ap.add_argument("--scene_thresh", type=float, default=0.4)
    ap.add_argument("--samples", type=int, default=5)
    a = ap.parse_args()

    tw, th = (int(x) for x in a.target.split("x"))
    sw, sh, fps, dur = probe(a.input)
    shots = scenes(a.input, dur, a.scene_thresh)

    fl = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=python.BaseOptions(model_asset_path=MODEL),
        running_mode=vision.RunningMode.IMAGE, num_faces=5))

    boxes = []
    td = tempfile.mkdtemp()
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
        tracks = track(dets)
        if tracks:
            box = facebox(rep(pick(tracks)), sw, sh, tw, th, a.face_frac, a.max_zoom)
            kind = "face"
        else:
            box = saliency(imgs, sw, sh, tw, th) if imgs else (
                even(min(sh, sw * tw / th)), even(min(sh, sw / (tw / th))),
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
