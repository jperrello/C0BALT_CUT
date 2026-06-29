#!/usr/bin/env python3
# Emit an ffmpeg filter_complex that hard-cuts each verified b-roll pick over the
# base 1080x1920 clip. Each b-roll input is cover-scaled to 1080x1920 then cropped
# toward its SUBJECT on the slack axis (not blind center, not background texture),
# time-shifted to its window start, gated by enable=between(t,t0,t1).
#
# Subject framing reuses fill-vertical's engine: sample several frames across the
# cutaway and pick the crop offset SUBJECT-FIRST — a face (MediaPipe), else a
# person (pose), else a thresholded multi-frame saliency centroid (resists the
# background-texture drift that a single-frame fine-grained centroid suffers).
# Still a full-bleed COVER crop (no bars, no extra punch-in) — only WHERE the
# crop sits changes. Degrades to centered when detectors/cv2 are unavailable.
# argv: plan.json  -> prints "<filter>;<n_inputs>" with valid picks count.
import json, sys, os, subprocess, tempfile

plan = json.load(open(sys.argv[1]))
W, H = 1080, 1920
picks = [p for p in plan.get("picks", [])
         if p.get("clip_path") and os.path.exists(p["clip_path"])]
picks.sort(key=lambda p: p["t0"])

if not picks:
    print("|0")
    sys.exit(0)

FILL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fill-vertical")


def even(v):
    v = int(round(v))
    return v - (v & 1)


def cover(w, h):
    sf = max(W / w, H / h)
    return even(w * sf), even(h * sf)


# lazily-built, reused-across-picks subject detectors.
_det = {"loaded": False, "fv": None, "face": None, "pose": None}


def detectors():
    if _det["loaded"]:
        return _det
    _det["loaded"] = True
    try:
        sys.path.insert(0, os.path.abspath(FILL_DIR))
        import fill_vertical as fv
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision
        _det["fv"] = fv
        _det["face"] = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mpp.BaseOptions(model_asset_path=fv.MODEL),
                running_mode=vision.RunningMode.IMAGE, num_faces=5))
    except Exception:
        _det["fv"] = None
    return _det


def grabframes(path, dur, n):
    # n frames evenly across the cutaway, decoded small (width 960) — detection is
    # in normalized coords so the working resolution is irrelevant to the result.
    try:
        import cv2
    except Exception:
        return []
    td = tempfile.mkdtemp()
    base = float(dur) if dur else None
    if base is None:
        try:
            base = float(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", path]))
        except Exception:
            base = None
    ts = [base * (i + 0.5) / n for i in range(n)] if base else [0.5]
    imgs = []
    for i, t in enumerate(ts):
        fp = os.path.join(td, "f%d.png" % i)
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.3f" % t,
                            "-i", path, "-frames:v", "1", "-vf", "scale=960:-2", fp],
                           check=True)
            img = cv2.imread(fp)
        except Exception:
            img = None
        if img is not None:
            imgs.append(img)
    return imgs


def salcenter(imgs):
    # thresholded multi-frame saliency centroid: only the concentrated salient mass
    # (above mean+std) votes, so diffuse background texture no longer drags the
    # centroid off the subject the way a raw weighted mean does.
    try:
        import cv2, numpy as np
    except Exception:
        return None
    sal = cv2.saliency.StaticSaliencyFineGrained_create()
    acc = None
    for img in imgs:
        ok, m = sal.computeSaliency(img)
        if not ok:
            continue
        acc = m if acc is None else acc + m
    if acc is None:
        return None
    mx = acc.max()
    if mx > 0:
        acc = acc / mx
    mask = (acc >= acc.mean() + acc.std()).astype("float32")
    if mask.sum() < 1:
        mask = acc
    tot = mask.sum() or 1
    h, w = mask.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w]
    return (float((xs * mask).sum() / tot / w),
            float((ys * mask).sum() / tot / h), "saliency")


def subject(path, dur):
    # normalized (nx, ny, kind) subject center across the cutaway, or None.
    imgs = grabframes(path, dur, 5)
    if not imgs:
        return None
    quorum = max(1, len(imgs) // 2)
    det = detectors()
    fv = det["fv"]
    if fv is not None:
        try:
            import numpy as np
            fcs = []
            for img in imgs:
                ds = fv.faces(det["face"], img)
                if ds:
                    f = max(ds, key=lambda d: d["w"] * d["h"])   # the dominant face
                    fcs.append((f["cx"], f["eye"]))
            if len(fcs) >= quorum:
                return (float(np.median([c[0] for c in fcs])),
                        float(np.median([c[1] for c in fcs])), "face")
            if det["pose"] is None:
                det["pose"] = fv.poselm()
            pcs = []
            for img in imgs:
                p = fv.person(det["pose"], img)
                if p:
                    pcs.append((p["cx"], p["head"]))
            if len(pcs) >= quorum:
                return (float(np.median([c[0] for c in pcs])),
                        float(np.median([c[1] for c in pcs])), "person")
        except Exception:
            pass
    return salcenter(imgs)


def crop_offsets(path, dur):
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", path])
        s = json.loads(out)["streams"][0]
        w, h = int(s["width"]), int(s["height"])
    except Exception:
        return W, H, 0, 0
    sw, sh = cover(w, h)
    sx, sy = max(0, sw - W), max(0, sh - H)
    if sx == 0 and sy == 0:
        return sw, sh, 0, 0
    sc = subject(path, dur)
    if sc is None:
        return sw, sh, even(sx / 2), even(sy / 2)   # centered fallback
    nx, ny, kind = sc
    if sx >= sy:                              # horizontal slack -> follow nx
        return sw, sh, even(min(max(nx * sw - W / 2, 0), sx)), even(sy / 2)
    anchor = ny * sh - (H / 3 if kind == "face" else H / 2)   # face -> eyeline upper third
    return sw, sh, even(sx / 2), even(min(max(anchor, 0), sy))


parts = []
# input 0 is the base clip; b-roll inputs are 1..n
for i, p in enumerate(picks):
    idx = i + 1
    t0 = float(p["t0"])
    src = p.get("source", {})
    dur = (float(src.get("t1_src", 0)) - float(src.get("t0_src", 0))) or None
    sw, sh, cx, cy = crop_offsets(p["clip_path"], dur)
    parts.append(
        f"[{idx}:v]scale={sw}:{sh},crop={W}:{H}:{cx}:{cy},"
        f"setsar=1,setpts=PTS-STARTPTS+{t0}/TB[bv{idx}]"
    )

last = "0:v"
ov = []
for i, p in enumerate(picks):
    idx = i + 1
    t0 = float(p["t0"]); t1 = float(p["t1"])
    out = f"o{idx}" if idx < len(picks) else "vout"
    ov.append(
        f"[{last}][bv{idx}]overlay=enable='between(t,{t0:.3f},{t1:.3f})'[{out}]"
    )
    last = out

flt = ";".join(parts + ov)
print(f"{flt}|{len(picks)}")
