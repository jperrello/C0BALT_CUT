#!/usr/bin/env python3
# Emit an ffmpeg filter_complex that hard-cuts each verified b-roll pick over the
# base 1080x1920 clip. Each b-roll input is cover-scaled to 1080x1920 then cropped
# toward its SALIENT region (not blind center), time-shifted to its window start,
# gated by enable=between(t,t0,t1).
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


def even(v):
    v = int(round(v))
    return v - (v & 1)


def cover(w, h):
    sf = max(W / w, H / h)
    return even(w * sf), even(h * sf)


def crop_offsets(path, dur):
    # cover-scaled dims + a saliency-chosen crop offset on the slack axis.
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
    try:
        import cv2, numpy as np
        td = tempfile.mkdtemp()
        fp = os.path.join(td, "f.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                        "-ss", "%.3f" % (float(dur) * 0.5 if dur else 0.5),
                        "-i", path, "-frames:v", "1",
                        "-vf", "scale=%d:%d" % (sw, sh), fp], check=True)
        img = cv2.imread(fp)
        if img is None:
            raise RuntimeError("no frame")
        sal = cv2.saliency.StaticSaliencyFineGrained_create()
        ok, m = sal.computeSaliency(img)
        if not ok:
            raise RuntimeError("saliency failed")
        if sx >= sy:                       # horizontal slack -> column centroid
            col = m.sum(axis=0)
            c = (np.arange(len(col)) * col).sum() / (col.sum() or 1)
            return sw, sh, even(min(max(c - W / 2, 0), sx)), even(sy / 2)
        row = m.sum(axis=1)                 # vertical slack -> row centroid
        c = (np.arange(len(row)) * row).sum() / (row.sum() or 1)
        return sw, sh, even(sx / 2), even(min(max(c - H / 2, 0), sy))
    except Exception:
        return sw, sh, even(sx / 2), even(sy / 2)   # centered fallback


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
