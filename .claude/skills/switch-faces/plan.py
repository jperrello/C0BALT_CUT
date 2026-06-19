#!/usr/bin/env python3
# Plan listener reaction-shot cutaways: detect a non-speaking second face in the
# 16:9 source and pick beat windows to hard-cut to it (the "react shot" a real
# editor inserts while the speaker lands a thought). Deterministic — no Claude.
# Reuses fill-vertical's face detection / identity clustering.
#
# Trigger = phrase boundaries (chunk-caption ends), the semantic version of a
# speech pause — raw audio gaps are gone by this stage (tighten-pace collapses
# every inter-word gap to ~0.08-0.15s). Falls back to a periodic word-snapped
# rhythm when no chunks.json is supplied.
#
# argv: source16x9.mp4 transcript.json [chunks.json]
#   -> {"src":[w,h], "windows":[{t0,t1,crop:[cw,ch,cx,cy]}]}
import os, sys, json, tempfile, importlib.util
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "fill_vertical", os.path.join(HERE, "..", "fill-vertical", "fill_vertical.py"))
fv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fv)

from mediapipe.tasks import python as mpp
from mediapipe.tasks.python import vision as mpv

LEAD = float(os.environ.get("SWITCH_LEAD", "2.8"))          # cold-open title owns the open
TAIL = float(os.environ.get("SWITCH_TAIL", "1.5"))          # stable landing
SPACING = float(os.environ.get("SWITCH_SPACING", "5.0"))    # min gap between switches
SEG = float(os.environ.get("SWITCH_SEG", "6.0"))            # fallback periodic rhythm
FACE_FRAC = float(os.environ.get("SWITCH_FACE_FRAC", "0.40"))  # listener framed a touch looser
HOLDS = [1.1, 0.9, 1.0, 0.8]                                # 0.8-1.2s reaction holds
TW, TH = 1080, 1920

src, tx_path = sys.argv[1], sys.argv[2]
chunks_path = sys.argv[3] if len(sys.argv) > 3 else ""
sw, sh, fps, dur = fv.probe(src)
words = json.load(open(tx_path)).get("words", []) if os.path.exists(tx_path) else []


def empty():
    json.dump({"src": [sw, sh], "windows": []}, sys.stdout)
    sys.exit(0)


fl = mpv.FaceLandmarker.create_from_options(mpv.FaceLandmarkerOptions(
    base_options=mpp.BaseOptions(model_asset_path=fv.MODEL),
    running_mode=mpv.RunningMode.IMAGE, num_faces=5))

td = tempfile.mkdtemp()
shotdata = []
for si, (a0, a1) in enumerate(fv.scenes(src, dur, 0.4)):
    n = max(2, 7 if (a1 - a0) > 0.5 else 2)
    ts = [a0 + (a1 - a0) * (i + 0.5) / n for i in range(n)]
    dets = []
    for i, t in enumerate(ts):
        img = fv.frame(src, min(t, dur - 0.05), td, si * 100 + i)
        if img is not None:
            dets.append(fv.faces(fl, img))
    shotdata.append((a0, a1, fv.track(dets), dets))

# cluster every track's identity signature across all shots; the longest-present
# identity is the dominant speaker (storyteller). Need >=2 identities to switch.
clusters = []
for a0, a1, tracks, _ in shotdata:
    for tr in tracks:
        s = fv.trsig(tr)
        best, bd = None, fv.SIG_THRESH
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

if len(clusters) < 2:
    empty()
dom = max(clusters, key=lambda c: c["dur"])["sig"]


def listener(tracks, dets):
    # only a TRUE two-shot qualifies: some sampled frame in this shot must hold
    # the dominant speaker AND a non-dominant face SIMULTANEOUSLY. This rejects
    # single-interview footage where identity drift splits one person across
    # shots into spurious "identities" (which would just punch into the speaker).
    def far(f):
        return float(np.linalg.norm(f["sig"] - dom)) >= fv.SIG_THRESH
    cooc = any(
        any(not far(f) for f in frame) and any(far(f) for f in frame)
        for frame in dets if len(frame) >= 2)
    if not cooc:
        return None
    # the listener = a non-dominant track; prefer the calmest (least lip motion),
    # which reads as someone listening rather than a second active speaker.
    cand = [tr for tr in tracks
            if float(np.linalg.norm(fv.trsig(tr) - dom)) >= fv.SIG_THRESH]
    if not cand:
        return None
    return fv.facebox(fv.rep(min(cand, key=fv.trackvar)),
                      sw, sh, TW, TH, FACE_FRAC, 2.0)


shots = [(a0, a1, listener(tracks, dets)) for a0, a1, tracks, dets in shotdata]


def shot(t):
    for j, (a0, a1, box) in enumerate(shots):
        if a0 <= t < a1:
            return j, box
    return -1, None


# candidate beats = phrase boundaries (chunk-caption ends). A thought landing is
# exactly where an editor cuts to the listener. Rank by the length of the phrase
# that just ended (longer thought -> stronger landing). Fall back to a periodic
# word-snapped rhythm when no chunks are available.
def snap(t):
    best = None
    for w in words:
        d = abs(float(w["t0"]) - t)
        if d <= 0.6 and (best is None or d < abs(best - t)):
            best = float(w["t0"])
    return best if best is not None else t


cands = []
chunks = json.load(open(chunks_path)).get("chunks", []) \
    if chunks_path and os.path.exists(chunks_path) else []
if chunks:
    for c in chunks[:-1]:                # never the final phrase (tail must land)
        span = float(c["t1"]) - float(c["t0"])
        cands.append((span, float(c["t1"])))
    cands.sort(key=lambda c: -c[0])      # longest thought first
else:
    t = LEAD + SEG
    while t < dur - TAIL:
        cands.append((0.0, round(snap(t), 3)))
        t += SEG

k = max(1, min(4, int(dur / 12)))
windows = []
hi = 0
for _, endw in cands:
    t0 = endw - 0.25                     # catch the speaker landing the line
    t1 = t0 + HOLDS[hi % len(HOLDS)]
    if t0 < LEAD or t1 > dur - TAIL:
        continue
    j0, box = shot(t0)
    j1, _ = shot(t1)
    if box is None or j0 < 0 or j0 != j1:   # listener must be present, whole window in one shot
        continue
    if any(abs(t0 - w["t0"]) < SPACING for w in windows):
        continue
    cw, ch, cx, cy = box
    windows.append({"t0": round(t0, 3), "t1": round(t1, 3), "crop": [cw, ch, cx, cy]})
    hi += 1
    if len(windows) >= k:
        break

windows.sort(key=lambda w: w["t0"])
json.dump({"src": [sw, sh], "windows": windows}, sys.stdout)
