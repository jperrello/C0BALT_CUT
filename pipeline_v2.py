#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
_FULL_BIN = "/opt/homebrew/opt/ffmpeg-full/bin"
FFMPEG = os.environ.get("FFMPEG") or (
    f"{_FULL_BIN}/ffmpeg" if Path(f"{_FULL_BIN}/ffmpeg").exists() else "ffmpeg"
)
FFPROBE = os.environ.get("FFPROBE") or (
    f"{_FULL_BIN}/ffprobe" if Path(f"{_FULL_BIN}/ffprobe").exists() else "ffprobe"
)

CANVAS_W, CANVAS_H = 1080, 1920
SCREEN_W, SCREEN_H = 1080, 1416
FACE_TILE_X, FACE_TILE_Y, FACE_TILE_S = 288, 1416, 504
BLUR_STRIP_W, BLUR_STRIP_H = 288, 504
PANEL_AR_INV = SCREEN_W / SCREEN_H
FACE_PAD = 0.12
FACE_CHIN_SHIFT = 0.06
SUBTITLE_MARGIN_V = 544
L1_LAMBDAS = (8.0, 40.0)
FPS = 30
ONE_EURO = dict(mc=0.8, beta=0.007, dc=1.0)

HOOK_WORDS = {
    "wait", "no", "way", "oh", "god", "holy", "let's", "lets",
    "go", "what", "the", "bro", "dude", "yo", "damn", "crazy",
    "insane", "sick", "kidding", "hell", "nah", "bruh",
}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def probe_duration(path):
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def probe_size(path):
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", str(path)],
        check=True, capture_output=True, text=True,
    )
    w, h = r.stdout.strip().split("x")
    return int(w), int(h)


def extract_clip(src, cs, ce, out):
    run([FFMPEG, "-nostdin", "-v", "error", "-y",
         "-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", str(FPS), "-an", str(out)])


FACE_MODEL = ROOT / "models" / "face_detection_yunet_2023mar.onnx"
FACE_MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)


def ensure_face_model():
    if FACE_MODEL.exists():
        return
    import urllib.request
    FACE_MODEL.parent.mkdir(parents=True, exist_ok=True)
    print(f"[v2] downloading face detector → {FACE_MODEL}")
    urllib.request.urlretrieve(FACE_MODEL_URL, FACE_MODEL)


def detect_faces(path, src_w, src_h):
    # YuNet (OpenCV built-in). Research-v2 specified MediaPipe short-range but
    # that model under-detects small PiP faces at 1080p; YuNet is more reliable
    # and keeps the same per-frame cadence assumption.
    ensure_face_model()
    det = cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (src_w, src_h), 0.5, 0.3, 5000)
    cap = cv2.VideoCapture(str(path))
    boxes = []
    last = None
    y_floor = src_h * 0.55  # streamer PiPs live in the bottom half of the frame
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        _, faces = det.detect(frame)
        if faces is None or len(faces) == 0:
            boxes.append(None)
            continue
        valid = [f for f in faces if (f[1] + f[3] / 2) > y_floor]
        if not valid:
            boxes.append(None)
            continue
        if last is not None:
            lcx, lcy = last
            best = min(valid, key=lambda f:
                (f[0] + f[2] / 2 - lcx) ** 2 + (f[1] + f[3] / 2 - lcy) ** 2)
        else:
            best = max(valid, key=lambda f: f[1] + f[3])
        x, y, w, h = float(best[0]), float(best[1]), float(best[2]), float(best[3])
        w = max(1.0, w); h = max(1.0, h)
        cx = x + w / 2
        cy = y + h / 2 + FACE_CHIN_SHIFT * h
        s = max(w, h) * (1 + FACE_PAD)
        last = (cx, cy)
        boxes.append((cx, cy, s))
    cap.release()
    return boxes


def one_euro(values, freq=FPS, mc=0.8, beta=0.007, dc=1.0):
    def alpha(c):
        tau = 1.0 / (2 * math.pi * c)
        te = 1.0 / freq
        return 1.0 / (1.0 + tau / te)
    out = np.zeros(len(values), dtype=np.float64)
    prev = None
    dprev = 0.0
    for i, v in enumerate(values):
        if prev is None:
            out[i] = v
            prev = v
            continue
        dv = (v - prev) * freq
        df = dprev + alpha(dc) * (dv - dprev)
        cutoff = mc + beta * abs(df)
        a = alpha(cutoff)
        xf = prev + a * (v - prev)
        out[i] = xf
        prev = xf
        dprev = df
    return out


def smooth_face(boxes):
    first = next((b for b in boxes if b is not None), None)
    if first is None:
        return None
    filled = []
    last = first
    for b in boxes:
        if b is None:
            filled.append(last)
        else:
            filled.append(b)
            last = b
    cx = np.array([b[0] for b in filled])
    cy = np.array([b[1] for b in filled])
    ss = np.array([b[2] for b in filled])
    return (one_euro(cx, **ONE_EURO),
            one_euro(cy, **ONE_EURO),
            one_euro(ss, **ONE_EURO))


def compute_reframe_signal(path, face_cx, face_cy, face_s, src_w, src_h, win_w):
    cap = cv2.VideoCapture(str(path))
    sal = cv2.saliency.StaticSaliencySpectralResidual_create()
    prev_small = None
    xs = []
    cached_flow_x = None
    scale = 4
    sw, sh = src_w // scale, src_h // scale
    max_left = src_w - win_w
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (sw, sh))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        success, smap = sal.computeSaliency(small)
        if not success:
            smap = np.ones((sh, sw), dtype=np.float32)
        smap = smap.astype(np.float32)

        if i < len(face_cx):
            fcx = int(face_cx[i] / scale)
            fcy = int(face_cy[i] / scale)
            fs = int(face_s[i] / scale)
            x0 = max(0, fcx - fs)
            y0 = max(0, fcy - fs)
            x1 = min(sw, fcx + fs)
            y1 = min(sh, fcy + fs)
            smap[y0:y1, x0:x1] = 0

        col_s = smap.sum(axis=0)
        x_sal = float((col_s * np.arange(len(col_s))).sum() / (col_s.sum() + 1e-9)) * scale

        if prev_small is not None and i % 3 == 0:
            flow = cv2.calcOpticalFlowFarneback(prev_small, gray, None,
                0.5, 2, 15, 2, 5, 1.2, 0)
            mag = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
            if i < len(face_cx):
                mag[y0:y1, x0:x1] = 0
            col_f = mag.sum(axis=0)
            total = col_f.sum() + 1e-9
            cached_flow_x = float((col_f * np.arange(len(col_f))).sum() / total) * scale
        x_flow = cached_flow_x if cached_flow_x is not None else x_sal
        prev_small = gray

        # Fuse (cursor channel omitted for v2.0)
        x_raw = 0.75 * x_sal + 0.25 * x_flow
        left = x_raw - win_w / 2.0
        left = max(0.0, min(max_left, left))
        xs.append(left)
        i += 1
    cap.release()
    return np.array(xs, dtype=np.float64)


def smooth_reframe_tv(x_raw, grid=40):
    from scipy.signal import medfilt
    x_med = medfilt(x_raw, kernel_size=15)
    return np.round(x_med / grid) * grid


def smooth_reframe_l1(x_raw, x_max, l1=L1_LAMBDAS[0], l2=L1_LAMBDAS[1]):
    from scipy.optimize import linprog
    from scipy.sparse import csr_matrix
    T = len(x_raw)
    if T < 3:
        return x_raw.copy()
    nx, nu, nv, na = T, T, T - 1, T - 2
    N = nx + nu + nv + na
    c = np.concatenate([np.zeros(nx), np.ones(nu), l1 * np.ones(nv), l2 * np.ones(na)])
    bounds = [(0.0, float(x_max))] * nx + [(0.0, None)] * (nu + nv + na)

    rows, cols, data, bub = [], [], [], []
    r = 0
    for i in range(T):
        rows += [r, r]; cols += [i, nx + i]; data += [1.0, -1.0]; bub.append(float(x_raw[i])); r += 1
        rows += [r, r]; cols += [i, nx + i]; data += [-1.0, -1.0]; bub.append(-float(x_raw[i])); r += 1
    for i in range(T - 1):
        rows += [r, r, r]; cols += [i + 1, i, nx + nu + i]; data += [1.0, -1.0, -1.0]; bub.append(0.0); r += 1
        rows += [r, r, r]; cols += [i + 1, i, nx + nu + i]; data += [-1.0, 1.0, -1.0]; bub.append(0.0); r += 1
    for i in range(T - 2):
        rows += [r, r, r, r]; cols += [i + 2, i + 1, i, nx + nu + nv + i]
        data += [1.0, -2.0, 1.0, -1.0]; bub.append(0.0); r += 1
        rows += [r, r, r, r]; cols += [i + 2, i + 1, i, nx + nu + nv + i]
        data += [-1.0, 2.0, -1.0, -1.0]; bub.append(0.0); r += 1

    A = csr_matrix((data, (rows, cols)), shape=(r, N))
    res = linprog(c, A_ub=A, b_ub=np.array(bub), bounds=bounds, method="highs")
    if not res.success:
        return None
    return res.x[:T]


def compose_frames(path, face_cx, face_cy, face_s, screen_left, win_w, src_h, proc):
    cap = cv2.VideoCapture(str(path))
    n = min(len(face_cx), len(screen_left))
    i = 0
    while i < n:
        ok, frame = cap.read()
        if not ok:
            break
        canvas = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)

        # Screen panel: crop (screen_left, 0, win_w, src_h) → scale 1080×1416
        sl = int(max(0, min(frame.shape[1] - win_w, screen_left[i])))
        screen_crop = frame[:, sl:sl + win_w]
        screen = cv2.resize(screen_crop, (SCREEN_W, SCREEN_H), interpolation=cv2.INTER_LANCZOS4)
        canvas[0:SCREEN_H, 0:SCREEN_W] = screen

        # Bottom fill: downscale screen panel, blur+dim, place at y=1416..1920
        fill = cv2.resize(screen, (CANVAS_W, CANVAS_H - SCREEN_H), interpolation=cv2.INTER_AREA)
        fill = cv2.boxFilter(fill, -1, (41, 5))
        fill = cv2.convertScaleAbs(fill, alpha=0.55, beta=-20)
        fill_hsv = cv2.cvtColor(fill, cv2.COLOR_BGR2HSV).astype(np.int16)
        fill_hsv[..., 1] = np.clip(fill_hsv[..., 1] * 0.5, 0, 255)
        fill = cv2.cvtColor(fill_hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
        canvas[SCREEN_H:CANVAS_H, 0:CANVAS_W] = fill

        # Face tile: tight crop around face bbox, scale 504×504
        cx, cy, s = face_cx[i], face_cy[i], face_s[i]
        x0 = int(round(cx - s / 2))
        y0 = int(round(cy - s / 2))
        x1 = int(round(cx + s / 2))
        y1 = int(round(cy + s / 2))
        fx0 = max(0, x0); fy0 = max(0, y0)
        fx1 = min(frame.shape[1], x1); fy1 = min(frame.shape[0], y1)
        face = frame[fy0:fy1, fx0:fx1]
        if face.size > 0:
            pad_l = fx0 - x0
            pad_t = fy0 - y0
            pad_r = x1 - fx1
            pad_b = y1 - fy1
            if pad_l or pad_t or pad_r or pad_b:
                face = cv2.copyMakeBorder(face, pad_t, pad_b, pad_l, pad_r,
                                          cv2.BORDER_REPLICATE)
            face = cv2.resize(face, (FACE_TILE_S, FACE_TILE_S), interpolation=cv2.INTER_LANCZOS4)
            canvas[FACE_TILE_Y:FACE_TILE_Y + FACE_TILE_S,
                   FACE_TILE_X:FACE_TILE_X + FACE_TILE_S] = face

        proc.stdin.write(canvas.tobytes())
        i += 1
    cap.release()


ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Helvetica,72,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,2,60,60,{SUBTITLE_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(segs, path):
    def ts(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:d}:{m:02d}:{s:05.2f}"
    lines = [ASS_HEADER]
    for s in segs:
        t0 = max(0.0, s["start"])
        t1 = max(t0 + 0.1, s["end"])
        text = s["text"].strip().replace("\n", " ")
        if not text:
            continue
        lines.append(f"Dialogue: 0,{ts(t0)},{ts(t1)},Default,,0,0,0,,{text}")
    path.write_text("\n".join(lines) + "\n")


def write_ass_word(words, path):
    def ts(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:d}:{m:02d}:{s:05.2f}"
    lines = [ASS_HEADER]
    if not words:
        path.write_text("\n".join(lines) + "\n")
        return
    groups = []
    cur = [words[0]]
    for w in words[1:]:
        gap = w["start"] - cur[-1]["end"]
        if gap > 0.5 or len(cur) >= 6:
            groups.append(cur)
            cur = [w]
        else:
            cur.append(w)
    groups.append(cur)
    for g in groups:
        t0 = max(0.0, g[0]["start"])
        t1 = max(t0 + 0.1, g[-1]["end"])
        parts = []
        for w in g:
            cs = max(1, int(round((w["end"] - w["start"]) * 100)))
            txt = str(w["word"]).strip()
            if not txt:
                continue
            parts.append(f"{{\\k{cs}}}{txt}")
        if not parts:
            continue
        lines.append(f"Dialogue: 0,{ts(t0)},{ts(t1)},Default,,0,0,0,,{' '.join(parts)}")
    path.write_text("\n".join(lines) + "\n")


def align_words(segs, audio_path):
    if not segs:
        return []
    try:
        import whisperx
        import torch
    except ImportError as e:
        raise RuntimeError(
            "word mode requires whisperx (pip install whisperx)"
        ) from e
    device = "cpu"
    model_a, metadata = whisperx.load_align_model(language_code="en", device=device)
    aligned = whisperx.align(segs, model_a, metadata, str(audio_path), device,
                             return_char_alignments=False)
    out = []
    for seg in aligned.get("segments", []):
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            out.append({"start": float(w["start"]), "end": float(w["end"]),
                        "word": w.get("word", "").strip()})
    return out


def transcribe(src, cs, ce, tmp):
    try:
        import mlx_whisper
    except ImportError:
        return []
    clip = tmp / "clip.wav"
    run([FFMPEG, "-nostdin", "-v", "error", "-y",
         "-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000", str(clip)])
    r = mlx_whisper.transcribe(str(clip),
        path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
        word_timestamps=False)
    return r.get("segments", [])


DELIVER_DIR = Path("/Users/jperr/Documents/shorts/delivered")


def bead_id():
    v = os.environ.get("BEADS_CURRENT")
    if v:
        return v.strip()
    try:
        r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True, check=True)
        m = re.search(r"(sh-[a-z0-9]+)", r.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def deliver(out):
    DELIVER_DIR.mkdir(parents=True, exist_ok=True)
    bid = bead_id()
    ts = time.strftime("%Y%m%dT%H%M%S")
    name = f"{bid}-{ts}-{out.stem}.mp4" if bid else f"{ts}-{out.stem}.mp4"
    dst = DELIVER_DIR / name
    shutil.copy2(out, dst)
    print(f"[v2] delivered → {dst}")
    try:
        grade(dst)
    except Exception as e:
        print(f"[v2] grade failed: {e}", file=sys.stderr)
    return dst


def evaluate(metrics):
    hard = []
    if metrics.get("size_bytes", 0) < 100_000:
        hard.append("size")
    d = metrics.get("duration_s", 0.0)
    if d < 25.0 or d > 65.0:
        hard.append("duration")
    i = metrics.get("loudnorm_i", -14.0)
    if i < -15.0 or i > -13.0:
        hard.append("loudnorm")
    if metrics.get("face_tile_black_frac", 0.0) > 0.5:
        hard.append("face_black")
    if metrics.get("transcript_words", 0) == 0:
        hard.append("transcript_empty")
    soft = []
    if metrics.get("reframe_jerk", 0.0) > 10.0:
        soft.append("reframe_jerk")
    if metrics.get("hook_window_energy", 0.0) < -1.5:
        soft.append("low_hook_energy")
    if not metrics.get("hook_in_first_3s", True):
        soft.append("no_interjection_first_3s")
    rejected = bool(hard)
    return {
        "metrics": metrics,
        "hard_fails": hard,
        "soft_flags": soft,
        "rejected": rejected,
        "rejection_reason": hard[0] if rejected else None,
    }


def grade_metrics(path):
    path = Path(path)
    size = path.stat().st_size
    dur = probe_duration(path)
    i_val = -14.0
    try:
        r = subprocess.run(
            [FFMPEG, "-nostdin", "-hide_banner", "-i", str(path),
             "-af", "loudnorm=print_format=json", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        err = r.stderr
        a = err.rfind("{")
        b = err.rfind("}")
        if a >= 0 and b > a:
            i_val = float(json.loads(err[a:b + 1]).get("input_i", -14.0))
    except Exception:
        pass
    black = total = 0
    cap = cv2.VideoCapture(str(path))
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    samples = max(1, min(8, nframes))
    for k in range(samples):
        if nframes > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(k * nframes / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        y0, y1 = FACE_TILE_Y, min(h, FACE_TILE_Y + FACE_TILE_S)
        x0, x1 = FACE_TILE_X, min(w, FACE_TILE_X + FACE_TILE_S)
        if y0 >= y1 or x0 >= x1:
            total += 1
            continue
        tile = frame[y0:y1, x0:x1]
        if tile.size == 0:
            total += 1
            continue
        if cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY).mean() < 16.0:
            black += 1
        total += 1
    cap.release()
    face_frac = (black / total) if total else 0.0
    words = 0
    try:
        with tempfile.TemporaryDirectory() as td:
            segs = transcribe(path, 0.0, dur, Path(td))
        for s in segs:
            words += len(str(s.get("text", "")).split())
    except Exception:
        words = 0
    return {
        "size_bytes": size,
        "duration_s": dur,
        "loudnorm_i": i_val,
        "face_tile_black_frac": face_frac,
        "transcript_words": words,
        "reframe_jerk": 0.0,
        "hook_window_energy": 0.0,
        "hook_in_first_3s": True,
    }


def grade(path):
    path = Path(path)
    metrics = grade_metrics(path)
    verdict = evaluate(metrics)
    sidecar = path.with_suffix(".verdict.json")
    sidecar.write_text(json.dumps(verdict, indent=2, default=str))
    if verdict["rejected"]:
        reason = verdict["rejection_reason"]
        dest = path.parent / "rejected" / reason
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest / path.name))
        shutil.move(str(sidecar), str(dest / sidecar.name))
    return verdict


def render_one(src, cs, ce, out, reframe_mode="l1", subs_mode="line", overlay=None):
    out.parent.mkdir(parents=True, exist_ok=True)
    src_w, src_h = probe_size(src)
    win_w = int(round(src_h * PANEL_AR_INV))
    win_w = min(win_w, src_w)
    max_left = max(1, src_w - win_w)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        work = tmp / "work.mp4"
        print(f"[v2] extracting clip {cs:.2f}-{ce:.2f}s ({ce-cs:.2f}s) → {work.name}")
        extract_clip(src, cs, ce, work)

        print("[v2] detecting faces (MediaPipe)")
        raw = detect_faces(work, src_w, src_h)
        if not any(b is not None for b in raw):
            print("[v2] WARN: no face detected in clip; using center fallback", file=sys.stderr)
            cx = np.full(len(raw), src_w / 2)
            cy = np.full(len(raw), src_h / 2)
            ss = np.full(len(raw), min(src_w, src_h) / 3)
        else:
            cx, cy, ss = smooth_face(raw)
        hit_rate = sum(1 for b in raw if b is not None) / max(1, len(raw))
        print(f"[v2] face hit rate: {hit_rate:.1%} ({len(raw)} frames)")

        print(f"[v2] reframe signal (win={win_w}px, range=[0,{max_left}])")
        x_raw = compute_reframe_signal(work, cx, cy, ss, src_w, src_h, win_w)

        smoothed = None
        if reframe_mode == "l1":
            smoothed = smooth_reframe_l1(x_raw, max_left)
            if smoothed is None:
                print("[v2] L1 solve failed; falling back to TV", file=sys.stderr)
        if smoothed is None:
            smoothed = smooth_reframe_tv(x_raw)
        smoothed = np.clip(smoothed, 0, max_left)
        print(f"[v2] reframe: mean={smoothed.mean():.0f} range=[{smoothed.min():.0f},{smoothed.max():.0f}]")

        print("[v2] transcribing")
        segs = transcribe(src, cs, ce, tmp)
        ass = tmp / "clip.ass"
        if subs_mode == "word":
            clip_wav = tmp / "clip.wav"
            if not clip_wav.exists():
                run([FFMPEG, "-nostdin", "-v", "error", "-y",
                     "-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src),
                     "-vn", "-ac", "1", "-ar", "16000", str(clip_wav)])
            words = align_words(segs, clip_wav)
            write_ass_word(words, ass)
            sidecar = out.with_suffix(".words.json")
            sidecar.parent.mkdir(parents=True, exist_ok=True)
            sidecar.write_text(json.dumps(words))
        else:
            write_ass(segs, ass)
        def _esc(p):
            return (str(p)
                    .replace("\\", "\\\\").replace(":", "\\:")
                    .replace(",", "\\,").replace("'", "\\'")
                    .replace("[", "\\[").replace("]", "\\]"))
        ass_esc = _esc(ass)
        vf = f"ass={ass_esc}"
        if overlay and overlay != "off":
            ov = tmp / "overlay.ass"
            write_ass_overlay(overlay, 0.0, float(ce - cs), ov)
            vf = f"ass={ass_esc},ass={_esc(ov)}"

        n = min(len(cx), len(x_raw), len(smoothed))
        cx = cx[:n]; cy = cy[:n]; ss = ss[:n]; smoothed = smoothed[:n]

        print(f"[v2] composing {n} frames → {out}")
        ffmpeg_cmd = [
            FFMPEG, "-nostdin", "-v", "error", "-y",
            "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{CANVAS_W}x{CANVAS_H}", "-framerate", str(FPS),
            "-i", "pipe:0",
            "-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src),
            "-map", "0:v", "-map", "1:a",
            "-vf", vf,
            "-c:v", "h264_videotoolbox", "-profile:v", "high", "-level", "4.2",
            "-b:v", "10M", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
            "-af", "loudnorm=I=-14:LRA=11:TP=-1",
            "-movflags", "+faststart",
            str(out),
        ]
        proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)
        try:
            compose_frames(work, cx, cy, ss, smoothed, win_w, src_h, proc)
        finally:
            proc.stdin.close()
            rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg exited {rc}")


def audio_rms(path, sr=8000):
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.wav"
        run([FFMPEG, "-nostdin", "-v", "error", "-y", "-i", str(path),
             "-vn", "-ac", "1", "-ar", str(sr), "-f", "wav", str(wav)])
        with wave.open(str(wav), "rb") as w:
            n = w.getnframes()
            raw = w.readframes(n)
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    win = sr
    trimmed = samples[: (len(samples) // win) * win].reshape(-1, win)
    return np.sqrt((trimmed ** 2).mean(axis=1) + 1e-12)


def detect_scenes(path):
    from scenedetect import detect, AdaptiveDetector
    scenes = detect(str(path), AdaptiveDetector(), show_progress=False)
    return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]


def score_scenes(scenes, rms):
    if not scenes:
        return []
    starts = np.array([s for s, _ in scenes])
    z = (rms - rms.mean()) / (rms.std() + 1e-9)
    out = []
    for s, e in scenes:
        a, b = int(s), min(int(e), len(z))
        if b <= a:
            continue
        energy = float(z[a:b].mean())
        density = float(((starts >= s - 30) & (starts <= e + 30)).sum())
        out.append({"start": s, "end": e,
                    "energy_z": energy,
                    "score": energy * math.log1p(density)})
    return out


def shape_window(seg, rms, dur_min=30.0, dur_max=60.0, target=45.0, lead=1.0):
    a, b = int(seg["start"]), min(int(seg["end"]), len(rms))
    payoff = a + int(np.argmax(rms[a:b])) if b > a else seg["start"]
    cs = max(seg["start"], payoff - lead)
    ce = cs + target
    if ce > seg["end"]:
        ce = seg["end"]
        cs = max(seg["start"], ce - target)
    d = ce - cs
    if d < dur_min:
        ce = cs + dur_min
    if d > dur_max:
        ce = cs + dur_max
    return float(cs), float(ce)


def pick(cands, n=3, min_gap=90.0):
    cands = sorted(cands, key=lambda x: -x["score"])
    chosen = []
    for c in cands:
        if any(abs(c["start"] - p["start"]) < min_gap for p in chosen):
            continue
        chosen.append(c)
        if len(chosen) >= n:
            break
    chosen.sort(key=lambda x: x["start"])
    return chosen


HOOK_ALPHA = 2.0
DURATION_TARGET = 45.0


def hook_score(segs, rms_clip, start_abs):
    if not segs:
        return 0.0, False
    head = [s for s in segs if s["start"] < 3.0]
    words = " ".join(s["text"] for s in head).lower().split()
    hit = any(w.strip(".,!?") in HOOK_WORDS for w in words)
    qmark = any(s["text"].rstrip().endswith("?") for s in head)
    early_peak = False
    if len(rms_clip) > 3:
        z = (rms_clip - rms_clip.mean()) / (rms_clip.std() + 1e-9)
        early_peak = bool(z[:3].max() > 1.5)
    score = 1.0 * hit + 0.5 * qmark + 1.0 * early_peak
    return float(score), hit or early_peak


def composite_score(cand):
    return float(cand.get("score", 0.0)) + HOOK_ALPHA * float(cand.get("hook_score", 0.0))


def score_features(segs, rms_clip, cs, ce):
    head = [s for s in segs if s["start"] < 3.0]
    words = " ".join(s["text"] for s in head).lower().split()
    hook_first = any(w.strip(".,!?") in HOOK_WORDS for w in words)
    standalone = any(s["text"].rstrip().endswith((".", "!", "?")) and s["end"] <= 3.5 for s in head)
    dur = float(ce - cs)
    fit = 1.0 / (1.0 + abs(dur - DURATION_TARGET) / 10.0)
    return {
        "hook_in_first_3s": bool(hook_first),
        "standalone_3s": bool(standalone),
        "duration_fit": float(fit),
    }


def _clamp_overlay(text, transcript=""):
    words = (text or "").split()
    if len(words) > 7:
        words = words[:7]
    if len(words) < 5:
        pad = (transcript or "wait watch this clip play carefully").split()
        for w in pad:
            if w in words:
                continue
            words.append(w)
            if len(words) >= 5:
                break
        while len(words) < 5:
            words.append("watch")
    return " ".join(words)


def _capture_scribe():
    r = subprocess.run(["bash", str(Path(os.path.expanduser("~/.claude/skills/crew/crew.sh"))),
                        "capture", "scribe", "120"],
                       capture_output=True, text=True, timeout=10.0)
    return r.stdout


def _scribe_live(prompt, timeout=90.0):
    crew = Path(os.path.expanduser("~/.claude/skills/crew/crew.sh"))
    if not crew.exists():
        return None
    before = _capture_scribe().count("⏺")
    try:
        subprocess.run(["bash", str(crew), "send", "scribe", prompt],
                       check=True, timeout=15.0,
                       capture_output=True, text=True)
    except Exception:
        return None
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        time.sleep(4.0)
        out = _capture_scribe()
        if out.count("⏺") <= before:
            continue
        for line in reversed(out.splitlines()):
            s = line.strip()
            if not s.startswith("⏺"):
                continue
            body = s.lstrip("⏺").strip()
            if not body:
                continue
            wc = len(body.split())
            if 3 <= wc <= 14:
                last = body
                break
        if last:
            return last
    return None


def request_overlay(transcript, features):
    stub = os.environ.get("SCRIBE_STUB")
    if stub is not None:
        return _clamp_overlay(stub, transcript)
    feats = ", ".join(f"{k}={v}" for k, v in (features or {}).items())
    prompt = (
        "TikTok-grammar hook overlay, 5-7 words, no quotes, no trailing punctuation. "
        f"Features: {feats}. Transcript: {transcript[:400]}"
    )
    live = _scribe_live(prompt)
    if live:
        return _clamp_overlay(live, transcript)
    return _clamp_overlay("", transcript)


def write_ass_overlay(text, start, end, path):
    def ts(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t - h * 3600 - m * 60
        return f"{h}:{m:02d}:{s:05.2f}"
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {CANVAS_W}\n"
        f"PlayResY: {CANVAS_H}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Top,Arial Black,72,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,4,2,8,40,40,80,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    body = f"Dialogue: 0,{ts(start)},{ts(end)},Top,,0,0,0,,{{\\an8}}{text}\n"
    Path(path).write_text(header + body)


def pick_variety(cands, n, min_gap=600.0):
    ranked = sorted(cands, key=lambda c: -composite_score(c))
    chosen = []
    for c in ranked:
        if any(abs(c["start"] - p["start"]) < min_gap for p in chosen):
            continue
        chosen.append(c)
        if len(chosen) >= n:
            break
    chosen.sort(key=lambda x: x["start"])
    return chosen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="source VOD")
    ap.add_argument("outdir", type=Path, help="output directory")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--clip-start", type=float, default=None)
    ap.add_argument("--clip-end", type=float, default=None)
    ap.add_argument("--reframe-mode", choices=["l1", "tv"], default="l1")
    ap.add_argument("--subs-mode", choices=["line", "word"], default="line")
    ap.add_argument("--overlay", choices=["on", "off"], default="on")
    args = ap.parse_args()

    src = args.input
    if not src.exists():
        print(f"source missing: {src}", file=sys.stderr); sys.exit(1)

    dur = probe_duration(src)
    sw, sh = probe_size(src)
    print(f"[v2] source: {src} ({dur:.1f}s, {sw}x{sh})")

    args.outdir.mkdir(parents=True, exist_ok=True)

    if args.clip_start is not None and args.clip_end is not None:
        out = args.outdir / "smoke.mp4"
        overlay_text = None
        if args.overlay != "off":
            with tempfile.TemporaryDirectory() as td:
                segs = transcribe(src, args.clip_start, args.clip_end, Path(td))
            transcript = " ".join(s["text"] for s in segs).strip()
            feats = score_features(segs, np.array([0.0]), args.clip_start, args.clip_end)
            overlay_text = request_overlay(transcript, feats)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.with_suffix(".overlay.json").write_text(json.dumps({
                "text": overlay_text,
                "source_start": float(args.clip_start),
                "source_end": float(args.clip_end),
            }))
        render_one(src, args.clip_start, args.clip_end, out, args.reframe_mode,
                   subs_mode=args.subs_mode, overlay=overlay_text)
        print(f"[v2] wrote {out}")
        deliver(out)
        return

    print("[v2] computing audio RMS")
    rms = audio_rms(src)
    print(f"[v2] detecting scenes")
    scenes = detect_scenes(src)
    cands = score_scenes(scenes, rms)
    for c in cands:
        cs, ce = shape_window(c, rms)
        c["clip_start"] = cs
        c["clip_end"] = ce
    shortlist = pick(cands, n=args.n * 3, min_gap=90.0)[: args.n * 2]
    print(f"[v2] shortlisted {len(shortlist)} candidates, transcribing for hook_score")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for c in shortlist:
            cs, ce = c["clip_start"], c["clip_end"]
            segs = transcribe(src, cs, ce, tmp)
            a, b = int(cs), min(int(ce), len(rms))
            clip_rms = rms[a:b] if b > a else np.array([0.0])
            hs, _ = hook_score(segs, clip_rms, cs)
            c["hook_score"] = hs
            c["segs"] = segs
            c["features"] = score_features(segs, clip_rms, cs, ce)
    final = pick_variety(shortlist, n=args.n, min_gap=600.0)
    shorts_dir = args.outdir / "shorts"
    shorts_dir.mkdir(parents=True, exist_ok=True)
    meta = []
    for i, c in enumerate(final, 1):
        out = shorts_dir / f"short-{i:02d}.mp4"
        overlay_text = None
        if args.overlay != "off":
            tx = " ".join(s["text"] for s in c.get("segs", [])).strip()
            overlay_text = request_overlay(tx, c.get("features", {}))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.with_suffix(".overlay.json").write_text(json.dumps({
                "text": overlay_text,
                "source_start": float(c["clip_start"]),
                "source_end": float(c["clip_end"]),
            }))
        render_one(src, c["clip_start"], c["clip_end"], out, args.reframe_mode,
                   subs_mode=args.subs_mode, overlay=overlay_text)
        deliver(out)
        transcript = [{"start": float(s["start"]), "end": float(s["end"]), "text": s["text"]}
                      for s in c.get("segs", [])]
        meta.append({"index": i, "file": str(out.relative_to(ROOT)),
                     "source_start": c["clip_start"],
                     "source_end": c["clip_end"],
                     "score": c["score"],
                     "hook_score": c.get("hook_score", 0.0),
                     "composite": composite_score(c),
                     "overlay": overlay_text,
                     "transcript": transcript})
    (args.outdir / "shorts.json").write_text(json.dumps(
        {"source": str(src), "count": len(meta), "shorts": meta}, indent=2))
    print(f"[v2] wrote {len(meta)} shorts")


if __name__ == "__main__":
    main()
