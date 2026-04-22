#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
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

# Layout constants from research-v2.md §7
CANVAS_W, CANVAS_H = 1080, 1920
SCREEN_X, SCREEN_Y, SCREEN_W, SCREEN_H = 0, 0, 1080, 1416
FACE_X, FACE_Y, FACE_S = 288, 1416, 504
BLUR_L_X, BLUR_R_X = 0, 792
BLUR_STRIP_W, BLUR_STRIP_H = 288, 504
SUBTITLE_MARGIN_V = 544

FACE_PAD = 0.12
FACE_CHIN_SHIFT = 0.06
ONE_EURO = dict(min_cutoff=0.8, beta=0.007, d_cutoff=1.0)
REFRAME_FUSION = dict(sal=0.45, curs=0.0, flow=0.15)  # no cursor detector yet
TV_MEDFILT_KERNEL = 15
TV_SNAP_GRID = 40

HOOK_WORDS = {
    "wait", "no", "way", "oh", "god", "holy", "let's", "lets",
    "go", "what", "the", "bro", "dude", "yo", "damn", "crazy",
    "insane", "sick", "kidding", "hell", "nah", "bruh",
}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def probe_dur(p: Path) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(p)],
        check=True, capture_output=True, text=True)
    return float(r.stdout.strip())


def probe_size(p: Path) -> tuple[int, int]:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(p)],
        check=True, capture_output=True, text=True)
    w, h = r.stdout.strip().split("x")
    return int(w), int(h)


def probe_fps(p: Path) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(p)],
        check=True, capture_output=True, text=True)
    num, den = r.stdout.strip().split("/")
    return float(num) / float(den) if float(den) else 30.0


def detect_scenes(p: Path):
    from scenedetect import detect, AdaptiveDetector
    scenes = detect(str(p), AdaptiveDetector(), show_progress=False)
    return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]


def audio_rms(p: Path, sr: int = 8000) -> np.ndarray:
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "a.wav"
        run([FFMPEG, "-nostdin", "-v", "error", "-y", "-i", str(p),
             "-vn", "-ac", "1", "-ar", str(sr), "-f", "wav", str(wav)])
        with wave.open(str(wav), "rb") as w:
            raw = w.readframes(w.getnframes())
    s = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    win = sr
    t = s[: (len(s) // win) * win].reshape(-1, win)
    return np.sqrt((t ** 2).mean(axis=1) + 1e-12)


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
        out.append({"start": s, "end": e, "energy_z": energy,
                    "score": energy * math.log1p(density)})
    return out


def find_payoff(rms, s, e):
    a, b = int(s), min(int(e), len(rms))
    if b <= a:
        return s
    return a + int(np.argmax(rms[a:b]))


def shape_win(seg, rms, dur_min=30.0, dur_max=60.0, target=45.0, lead=1.0):
    payoff = find_payoff(rms, seg["start"], seg["end"])
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
    return float(cs), float(ce), float(payoff - cs)


def pick(cands, n=5, min_gap=60.0):
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


def transcribe(src: Path, cs: float, ce: float, tmp: Path):
    import mlx_whisper
    clip = tmp / "clip.wav"
    run([FFMPEG, "-nostdin", "-v", "error", "-y",
         "-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000", str(clip)])
    r = mlx_whisper.transcribe(
        str(clip),
        path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
        word_timestamps=False)
    return r.get("segments", [])


def hook_score(segs, rms_clip):
    if not segs:
        return 0.0
    head = [s for s in segs if s["start"] < 3.0]
    words = " ".join(s["text"] for s in head).lower().split()
    hit = any(w.strip(".,!?") in HOOK_WORDS for w in words)
    qmark = any(s["text"].rstrip().endswith("?") for s in head)
    peak = False
    if len(rms_clip) > 3:
        z = (rms_clip - rms_clip.mean()) / (rms_clip.std() + 1e-9)
        peak = bool(z[:3].max() > 1.5)
    return float(1.0 * hit + 0.5 * qmark + 1.0 * peak)


# --- One-Euro filter ---

class OneEuro:
    # Casiez et al. 2012; params per research-v2.md §3.
    def __init__(self, min_cutoff=0.8, beta=0.007, d_cutoff=1.0):
        self.mc = min_cutoff
        self.b = beta
        self.dc = d_cutoff
        self.x_prev = None
        self.dx_prev = 0.0
        self.t_prev = None

    def _alpha(self, cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.x_prev is None:
            self.x_prev = x
            self.t_prev = t
            return x
        dt = max(t - self.t_prev, 1e-6)
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(self.dc, dt)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        cutoff = self.mc + self.b * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev = x_hat
        self.dx_prev = dx_hat
        self.t_prev = t
        return x_hat


# --- Face detection (YuNet, per-frame) ---
# research-v2.md specifies MediaPipe short-range; YuNet is an equivalent
# per-frame face detector that drops in via cv2.FaceDetectorYN without a
# tflite bundle. Comparable recall, ~200fps on CPU.

YUNET_MODEL = ROOT / ".runtime/models/face_detection_yunet_2023mar.onnx"
YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/"
             "models/face_detection_yunet/face_detection_yunet_2023mar.onnx")


def ensure_yunet():
    if YUNET_MODEL.exists():
        return
    YUNET_MODEL.parent.mkdir(parents=True, exist_ok=True)
    print(f"[shorts] fetching YuNet model -> {YUNET_MODEL}")
    run(["curl", "-fsSL", "-o", str(YUNET_MODEL), YUNET_URL])


def detect_faces(frames, fps, sw, sh):
    ensure_yunet()
    det = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL), "", (sw, sh),
        score_threshold=0.6, nms_threshold=0.3, top_k=5)
    raw = []  # list of (cx, cy, s) or None
    for f in frames:
        _, faces = det.detect(f)
        if faces is None or len(faces) == 0:
            raw.append(None)
            continue
        # faces: rows of [x, y, w, h, 5 landmarks..., score]; pick largest
        best = max(faces, key=lambda r: r[2] * r[3])
        x, y, w, h = float(best[0]), float(best[1]), float(best[2]), float(best[3])
        cx = x + w / 2
        cy = y + h / 2 - FACE_CHIN_SHIFT * h
        s = max(w, h) * (1 + FACE_PAD)
        raw.append((cx, cy, s))

    # One-Euro smoothing with hold-last and decay.
    ex = OneEuro(**ONE_EURO)
    ey = OneEuro(**ONE_EURO)
    es = OneEuro(**ONE_EURO)
    smoothed = []
    last_hit = None
    gap = 0
    max_gap_frames = int(0.5 * fps)
    for i, r in enumerate(raw):
        t = i / fps
        if r is None:
            gap += 1
            if last_hit is None:
                smoothed.append(None)
            else:
                smoothed.append(last_hit if gap <= max_gap_frames else last_hit)
            continue
        gap = 0
        cx, cy, s = r
        cx = ex(cx, t)
        cy = ey(cy, t)
        s = es(s, t)
        last_hit = (cx, cy, s)
        smoothed.append(last_hit)
    # Backfill leading Nones with first good detection.
    first = next((v for v in smoothed if v is not None), None)
    if first is None:
        return [None] * len(raw)
    return [v if v is not None else first for v in smoothed]


# --- Screen reframe (saliency + flow fusion → TV-denoised trajectory) ---

def screen_trajectory(frames, sw, sh, pan_range, face_locs):
    sal_alg = cv2.saliency.StaticSaliencySpectralResidual_create()
    x_raw = np.zeros(len(frames), dtype=np.float32)
    prev_gray = None
    flow_centroid_prev = None
    for i, f in enumerate(frames):
        # Saliency
        small = cv2.resize(f, (sw // 2, sh // 2))
        ok, sal = sal_alg.computeSaliency(small)
        if not ok:
            sal = np.ones_like(small[:, :, 0], dtype=np.float32) * 0.5
        else:
            sal = sal.astype(np.float32)
        # Mask facecam region (Tyler1: bottom-right; also mask detected face).
        sh2, sw2 = sal.shape
        # Hardcoded bottom-right quadrant mask for embedded PiP
        sal[int(sh2 * 0.6):, int(sw2 * 0.6):] = 0.0
        if face_locs[i] is not None:
            fcx, fcy, fs = face_locs[i]
            x0 = max(0, int((fcx - fs / 2) / 2))
            y0 = max(0, int((fcy - fs / 2) / 2))
            x1 = min(sw2, int((fcx + fs / 2) / 2))
            y1 = min(sh2, int((fcy + fs / 2) / 2))
            sal[y0:y1, x0:x1] = 0.0
        col_mass = sal.sum(axis=0)
        if col_mass.sum() > 0:
            x_sal_small = float((np.arange(sw2) * col_mass).sum() / col_mass.sum())
            x_sal = x_sal_small * 2.0  # map back to full width
        else:
            x_sal = sw / 2.0
        # Flow centroid
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        small_gray = cv2.resize(gray, (sw // 4, sh // 4))
        if prev_gray is not None and i % 3 == 0:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, small_gray, None,
                0.5, 2, 15, 2, 5, 1.1, 0)
            mag = np.sqrt(flow[:, :, 0] ** 2 + flow[:, :, 1] ** 2)
            # Mask facecam region in flow too
            fh, fw = mag.shape
            mag[int(fh * 0.6):, int(fw * 0.6):] = 0.0
            col = mag.sum(axis=0)
            if col.sum() > 0:
                flow_centroid_prev = float((np.arange(fw) * col).sum() / col.sum()) * 4.0
        prev_gray = small_gray
        x_flow = flow_centroid_prev if flow_centroid_prev is not None else sw / 2.0
        w_s = REFRAME_FUSION["sal"]
        w_f = REFRAME_FUSION["flow"]
        x_center = (w_s * x_sal + w_f * x_flow) / (w_s + w_f)
        # Convert center-of-source to top-left of pan window, clamp.
        src_crop_w = int(round(sh * (SCREEN_W / SCREEN_H)))
        x_tl = x_center - src_crop_w / 2
        x_raw[i] = max(0.0, min(pan_range, x_tl))
    return x_raw


def smooth_tv(x_raw, kernel=TV_MEDFILT_KERNEL, snap=TV_SNAP_GRID):
    from scipy.signal import medfilt
    k = kernel if kernel % 2 == 1 else kernel + 1
    y = medfilt(x_raw.astype(np.float32), kernel_size=k)
    # Snap to grid to produce piecewise-constant segments (L1-like)
    y = np.round(y / snap) * snap
    return y


def smooth_l1(x_raw, lam1=8.0, lam2=40.0, max_x=None):
    # L1-regularized trajectory via scipy linprog (HiGHS).
    # Falls back to smooth_tv if it fails.
    try:
        from scipy.optimize import linprog
        T = len(x_raw)
        # Variables: x[0..T-1], u[0..T-2] (|dx|), v[0..T-3] (|d2x|), plus
        # residual y[0..T-1] (|x - x_raw|).
        n_x, n_u, n_v, n_y = T, T - 1, T - 2, T
        N = n_x + n_u + n_v + n_y
        c = np.zeros(N)
        c[n_x:n_x + n_u] = lam1
        c[n_x + n_u:n_x + n_u + n_v] = lam2
        c[n_x + n_u + n_v:] = 1.0
        rows_A, rows_b = [], []
        # u_i >= x[i+1] - x[i] ; u_i >= -(x[i+1] - x[i])
        for i in range(n_u):
            r1 = np.zeros(N); r1[i] = 1; r1[i + 1] = -1; r1[n_x + i] = -1
            rows_A.append(r1); rows_b.append(0.0)
            r2 = np.zeros(N); r2[i] = -1; r2[i + 1] = 1; r2[n_x + i] = -1
            rows_A.append(r2); rows_b.append(0.0)
        # v_i >= |x[i+2] - 2x[i+1] + x[i]|
        for i in range(n_v):
            r1 = np.zeros(N); r1[i] = 1; r1[i + 1] = -2; r1[i + 2] = 1
            r1[n_x + n_u + i] = -1
            rows_A.append(r1); rows_b.append(0.0)
            r2 = np.zeros(N); r2[i] = -1; r2[i + 1] = 2; r2[i + 2] = -1
            r2[n_x + n_u + i] = -1
            rows_A.append(r2); rows_b.append(0.0)
        # y_i >= |x_i - x_raw_i|
        for i in range(n_y):
            r1 = np.zeros(N); r1[i] = 1; r1[n_x + n_u + n_v + i] = -1
            rows_A.append(r1); rows_b.append(float(x_raw[i]))
            r2 = np.zeros(N); r2[i] = -1; r2[n_x + n_u + n_v + i] = -1
            rows_A.append(r2); rows_b.append(-float(x_raw[i]))
        A_ub = np.array(rows_A)
        b_ub = np.array(rows_b)
        bounds = [(0.0, max_x if max_x is not None else None)] * n_x + \
                 [(0.0, None)] * (n_u + n_v + n_y)
        res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
        if not res.success:
            raise RuntimeError(res.message)
        return res.x[:n_x]
    except Exception as ex:
        print(f"[shorts] L1 solve failed ({ex}); falling back to TV", file=sys.stderr)
        return smooth_tv(x_raw)


# --- Composition ---

def read_clip_frames(src: Path, cs: float, ce: float):
    # Re-encode a clip at 30fps to a temp file so cv2 can stream it
    # frame-accurately without seek drift.
    tmp_clip = Path(tempfile.mkstemp(suffix=".mp4")[1])
    run([FFMPEG, "-nostdin", "-v", "error", "-y",
         "-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src),
         "-an", "-r", "30", "-c:v", "libx264", "-preset", "ultrafast",
         "-crf", "18", "-pix_fmt", "yuv420p", str(tmp_clip)])
    cap = cv2.VideoCapture(str(tmp_clip))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()
    tmp_clip.unlink(missing_ok=True)
    return frames, fps


def composite_frame(src_frame, face_loc, screen_x, sw, sh):
    canvas = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
    # Screen panel
    src_crop_w = int(round(sh * (SCREEN_W / SCREEN_H)))
    x = int(max(0, min(sw - src_crop_w, round(screen_x))))
    screen_crop = src_frame[:, x:x + src_crop_w]
    screen_tile = cv2.resize(screen_crop, (SCREEN_W, SCREEN_H),
                             interpolation=cv2.INTER_LANCZOS4)
    canvas[SCREEN_Y:SCREEN_Y + SCREEN_H, SCREEN_X:SCREEN_X + SCREEN_W] = screen_tile
    # Blur strips: same screen crop, heavily blurred + darker + desaturated
    blur_src = cv2.resize(screen_crop, (BLUR_STRIP_W, BLUR_STRIP_H),
                          interpolation=cv2.INTER_LINEAR)
    blur = cv2.GaussianBlur(blur_src, (0, 0), sigmaX=20, sigmaY=20)
    hsv = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] *= 0.5
    hsv[..., 2] *= 0.85
    blur = cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)
    canvas[FACE_Y:FACE_Y + FACE_S, BLUR_L_X:BLUR_L_X + BLUR_STRIP_W] = blur
    canvas[FACE_Y:FACE_Y + FACE_S, BLUR_R_X:BLUR_R_X + BLUR_STRIP_W] = blur
    # Face tile
    if face_loc is not None:
        cx, cy, s = face_loc
        x0 = int(round(cx - s / 2))
        y0 = int(round(cy - s / 2))
        x1, y1 = x0 + int(round(s)), y0 + int(round(s))
        x0c, y0c = max(0, x0), max(0, y0)
        x1c, y1c = min(sw, x1), min(sh, y1)
        face_crop = src_frame[y0c:y1c, x0c:x1c]
        if face_crop.size > 0:
            # Pad if near edge so the face stays centered in the tile.
            pad_l = x0c - x0
            pad_t = y0c - y0
            pad_r = x1 - x1c
            pad_b = y1 - y1c
            if any((pad_l, pad_t, pad_r, pad_b)):
                face_crop = cv2.copyMakeBorder(
                    face_crop, pad_t, pad_b, pad_l, pad_r,
                    cv2.BORDER_REPLICATE)
            face_tile = cv2.resize(face_crop, (FACE_S, FACE_S),
                                   interpolation=cv2.INTER_LANCZOS4)
            canvas[FACE_Y:FACE_Y + FACE_S, FACE_X:FACE_X + FACE_S] = face_tile
    return canvas


# --- Subtitle (ASS) writer ---

ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {CANVAS_W}
PlayResY: {CANVAS_H}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Helvetica,68,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,2,60,60,{SUBTITLE_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(segs, path: Path):
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
        lines.append(f"Dialogue: 0,{ts(t0)},{ts(t1)},Default,,0,0,0,,{text}")
    path.write_text("\n".join(lines) + "\n")


# --- Render ---

def encode(src: Path, cs: float, ce: float, face_locs, screen_x, segs,
           frames, sw, sh, out: Path, tmp: Path):
    ass = tmp / "clip.ass"
    write_ass(segs, ass)
    ass_esc = (str(ass).replace("\\", "\\\\").replace(":", "\\:")
               .replace(",", "\\,").replace("'", "\\'")
               .replace("[", "\\[").replace("]", "\\]"))
    cmd = [
        FFMPEG, "-nostdin", "-v", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{CANVAS_W}x{CANVAS_H}", "-r", "30", "-i", "pipe:0",
        "-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src),
        "-filter_complex", f"[0:v]ass={ass_esc}[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "h264_videotoolbox", "-profile:v", "high", "-level", "4.2",
        "-b:v", "10M", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "256k", "-ar", "48000",
        "-af", "loudnorm=I=-14:LRA=11:TP=-1",
        "-movflags", "+faststart",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i, f in enumerate(frames):
        canvas = composite_frame(
            f, face_locs[i] if i < len(face_locs) else None,
            screen_x[i] if i < len(screen_x) else 0.0, sw, sh)
        proc.stdin.write(canvas.tobytes())
    proc.stdin.close()
    ret = proc.wait()
    if ret != 0:
        raise RuntimeError(f"ffmpeg exited {ret}")


def render_clip(src: Path, cs: float, ce: float, out: Path, tmp: Path,
                mode: str, transcribe_audio: bool):
    sw, sh = probe_size(src)
    src_crop_w = int(round(sh * (SCREEN_W / SCREEN_H)))
    pan_range = max(0, sw - src_crop_w)
    print(f"[shorts] source {sw}x{sh}, src_crop_w={src_crop_w}, pan_range={pan_range}")

    print(f"[shorts] reading clip {cs:.2f}-{ce:.2f}")
    frames, fps = read_clip_frames(src, cs, ce)
    print(f"[shorts] {len(frames)} frames @ {fps:.2f}fps")

    print(f"[shorts] detecting faces (MediaPipe, per-frame)")
    face_locs = detect_faces(frames, fps, sw, sh)
    n_hits = sum(1 for f in face_locs if f is not None)
    print(f"[shorts] face hit rate: {n_hits}/{len(face_locs)}")

    print(f"[shorts] computing screen reframe trajectory")
    x_raw = screen_trajectory(frames, sw, sh, pan_range, face_locs)
    if mode == "l1":
        screen_x = smooth_l1(x_raw, max_x=pan_range)
    else:
        screen_x = smooth_tv(x_raw)
    print(f"[shorts] reframe x range: {screen_x.min():.0f}..{screen_x.max():.0f}")

    segs = []
    if transcribe_audio:
        print(f"[shorts] transcribing audio")
        segs = transcribe(src, cs, ce, tmp)

    print(f"[shorts] encoding -> {out}")
    encode(src, cs, ce, face_locs, screen_x, segs, frames, sw, sh, out, tmp)


# --- CLI ---

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("outdir", type=Path)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--clip-start", type=float, default=None)
    ap.add_argument("--clip-end", type=float, default=None)
    ap.add_argument("--smoke", action="store_true",
                    help="output single smoke.mp4 in outdir")
    ap.add_argument("--reframe-mode", choices=["tv", "l1"], default="tv")
    ap.add_argument("--no-subs", action="store_true")
    args = ap.parse_args()

    src = args.input
    if not src.exists():
        print(f"input missing: {src}", file=sys.stderr)
        sys.exit(1)
    args.outdir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if args.clip_start is not None and args.clip_end is not None:
            name = "smoke.mp4" if args.smoke else "short-01.mp4"
            out = args.outdir / name
            render_clip(src, args.clip_start, args.clip_end, out, tmp,
                        args.reframe_mode, not args.no_subs)
            print(f"[shorts] wrote {out}")
            return

        # Plan mode: scene-detect + score + shape + pick N
        dur = probe_dur(src)
        sw, sh = probe_size(src)
        print(f"[shorts] source {src} ({dur:.1f}s, {sw}x{sh})")
        rms = audio_rms(src)
        scenes = detect_scenes(src)
        cands = score_scenes(scenes, rms)
        for c in cands:
            cs, ce, payoff_rel = shape_win(c, rms)
            c["clip_start"] = cs; c["clip_end"] = ce; c["payoff_rel"] = payoff_rel
        short = pick(cands, n=args.n * 3, min_gap=90.0)[: args.n * 2]
        scored = []
        for c in short:
            cs, ce = c["clip_start"], c["clip_end"]
            segs = transcribe(src, cs, ce, tmp) if not args.no_subs else []
            a, b = int(cs), min(int(ce), len(rms))
            c["hook_score"] = hook_score(segs, rms[a:b] if b > a else np.array([0.0]))
            c["segs"] = segs
            scored.append(c)
        scored.sort(key=lambda x: -(x["score"] + 2.0 * x["hook_score"]))
        final = pick(scored, n=args.n, min_gap=90.0)
        print(f"[shorts] final {len(final)} clips")
        for i, c in enumerate(final, 1):
            out = args.outdir / f"short-{i:02d}.mp4"
            render_clip(src, c["clip_start"], c["clip_end"], out, tmp,
                        args.reframe_mode, not args.no_subs)
        print(f"[shorts] done")


if __name__ == "__main__":
    main()
