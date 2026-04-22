#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

import os
import shutil

ROOT = Path(__file__).resolve().parent
_FULL_BIN = "/opt/homebrew/opt/ffmpeg-full/bin"
FFMPEG = os.environ.get("FFMPEG") or (
    f"{_FULL_BIN}/ffmpeg" if Path(f"{_FULL_BIN}/ffmpeg").exists() else "ffmpeg"
)
FFPROBE = os.environ.get("FFPROBE") or (
    f"{_FULL_BIN}/ffprobe" if Path(f"{_FULL_BIN}/ffprobe").exists() else "ffprobe"
)
SRC = ROOT / "source" / "stream.mp4"
INPUT = ROOT / "input"
OUT = ROOT / "output"
SHORTS_DIR = OUT / "shorts"
OUT.mkdir(exist_ok=True)
SHORTS_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1080, 1920
FACE_SIZE = 400
FACE_Y = 40
GAME_W, GAME_H = 1080, 1400
GAME_Y = 460

HOOK_WORDS = {
    "wait", "no", "way", "oh", "god", "holy", "let's", "lets",
    "go", "what", "the", "bro", "dude", "yo", "damn", "crazy",
    "insane", "sick", "kidding", "hell", "nah", "bruh",
}


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def probe_duration(path: Path) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def probe_size(path: Path) -> tuple[int, int]:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0:s=x", str(path)],
        check=True, capture_output=True, text=True,
    )
    w, h = r.stdout.strip().split("x")
    return int(w), int(h)


def detect_scenes(path: Path):
    from scenedetect import detect, AdaptiveDetector
    scenes = detect(str(path), AdaptiveDetector(), show_progress=False)
    return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]


def audio_rms(path: Path, sr: int = 8000) -> np.ndarray:
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


def score_scenes(scenes, rms):
    if not scenes:
        return []
    starts = np.array([s for s, _ in scenes])
    z = (rms - rms.mean()) / (rms.std() + 1e-9)
    out = []
    for i, (s, e) in enumerate(scenes):
        a, b = int(s), min(int(e), len(z))
        if b <= a:
            continue
        energy = float(z[a:b].mean())
        density = float(((starts >= s - 30) & (starts <= e + 30)).sum())
        out.append({
            "start": s, "end": e,
            "energy_z": energy, "score": energy * math.log1p(density),
        })
    return out


def load_warren(path: Path):
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    clips = data.get("clips") or data.get("segments") or data.get("spans") or []
    out = []
    for c in clips:
        s = c.get("start") or c.get("source_start") or c.get("clip_start")
        e = c.get("end") or c.get("source_end") or c.get("clip_end")
        if s is None or e is None:
            continue
        out.append({
            "start": float(s), "end": float(e),
            "score": float(c.get("standalone_score") or c.get("score") or 1.0),
            "energy_z": float(c.get("energy_z") or 0.0),
        })
    return out or None


def find_payoff(rms, s, e):
    a, b = int(s), min(int(e), len(rms))
    if b <= a:
        return s
    return a + int(np.argmax(rms[a:b]))


def shape_window(seg, rms, dur_min=30.0, dur_max=60.0, target=45.0, lead=1.0):
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


def transcribe(src: Path, cs: float, ce: float, tmp: Path):
    import mlx_whisper
    clip = tmp / "clip.wav"
    run([FFMPEG, "-nostdin", "-v", "error", "-y",
         "-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000", str(clip)])
    r = mlx_whisper.transcribe(str(clip), path_or_hf_repo="mlx-community/whisper-large-v3-mlx", word_timestamps=False)
    return r.get("segments", [])


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


def face_bbox(src: Path, cs: float, ce: float, sw: int, sh: int, tmp: Path):
    import cv2
    cas = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    times = np.linspace(cs + 1, ce - 1, 8)
    boxes = []
    for i, t in enumerate(times):
        f = tmp / f"f{i}.jpg"
        run([FFMPEG, "-nostdin", "-v", "error", "-y",
             "-ss", f"{t:.3f}", "-i", str(src), "-frames:v", "1",
             "-q:v", "2", str(f)])
        img = cv2.imread(str(f))
        if img is None:
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = cas.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(40, 40))
        if len(faces) == 0:
            continue
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        boxes.append((float(x), float(y), float(w), float(h)))
    if not boxes:
        return None
    arr = np.median(np.array(boxes), axis=0)
    x, y, w, h = arr
    pad = 0.25
    cx, cy = x + w / 2, y + h / 2
    s = max(w, h) * (1 + pad)
    x0 = max(0, cx - s / 2)
    y0 = max(0, cy - s / 2)
    s = min(s, sw - x0, sh - y0)
    return (float(x0), float(y0), float(s), float(s))


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Helvetica,72,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,2,60,60,220,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(segs: list, path: Path):
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


def render(src: Path, cs: float, ce: float, face_bb, segs, out: Path, tmp: Path, sw: int, sh: int):
    ass = tmp / "clip.ass"
    write_ass(segs, ass)
    game_ar = GAME_W / GAME_H
    gw = min(sw, int(sh * game_ar))
    gh = min(sh, int(gw / game_ar))
    gx = (sw - gw) // 2
    gy = (sh - gh) // 2
    if face_bb:
        fx, fy, fw, fh = face_bb
        face_chain = f"crop={int(fw)}:{int(fh)}:{int(fx)}:{int(fy)},scale={FACE_SIZE}:{FACE_SIZE}"
    else:
        s = min(sw, sh) // 3
        face_chain = f"crop={s}:{s}:{sw - s}:{sh - s},scale={FACE_SIZE}:{FACE_SIZE}"
    face_x = (W - FACE_SIZE) // 2
    ass_esc = str(ass).replace("\\", "\\\\").replace(":", "\\:").replace(",", "\\,").replace("'", "\\'").replace("[", "\\[").replace("]", "\\]")
    vf = (
        f"[0:v]split=2[a][b];"
        f"[a]{face_chain}[face];"
        f"[b]crop={gw}:{gh}:{gx}:{gy},scale={GAME_W}:{GAME_H},"
        f"pad={W}:{H}:0:{GAME_Y}:black[base];"
        f"[base][face]overlay={face_x}:{FACE_Y}[g2];"
        f"[g2]ass={ass_esc}[v]"
    )
    run([
        FFMPEG, "-nostdin", "-v", "error", "-y",
        "-ss", f"{cs:.3f}", "-to", f"{ce:.3f}", "-i", str(src),
        "-filter_complex", vf,
        "-map", "[v]", "-map", "0:a",
        "-c:v", "h264_videotoolbox", "-profile:v", "high", "-level", "4.2",
        "-b:v", "8M", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-af", "loudnorm=I=-14:LRA=11:TP=-1",
        "-movflags", "+faststart",
        str(out),
    ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=SRC)
    ap.add_argument("--scenes-cache", type=Path, default=OUT / "scenes.json")
    ap.add_argument("--rms-cache", type=Path, default=OUT / "rms.npy")
    ap.add_argument("--plan-cache", type=Path, default=OUT / "plan.json")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--warren", type=Path, default=INPUT / "edit-instructions.json")
    args = ap.parse_args()

    src = args.src
    if not src.exists():
        print(f"source missing: {src}", file=sys.stderr)
        sys.exit(1)

    dur = probe_duration(src)
    sw, sh = probe_size(src)
    print(f"[shorts] source: {src} ({dur:.1f}s, {sw}x{sh})")

    warren = load_warren(args.warren)
    if warren:
        print(f"[shorts] loaded {len(warren)} Warren candidates")

    if args.rms_cache.exists():
        rms = np.load(args.rms_cache)
    else:
        print("[shorts] computing audio RMS")
        rms = audio_rms(src)
        np.save(args.rms_cache, rms)
    print(f"[shorts] {len(rms)}s of audio")

    if warren:
        cands = warren
    else:
        if args.scenes_cache.exists():
            scenes = [tuple(x) for x in json.loads(args.scenes_cache.read_text())]
        else:
            print("[shorts] detecting scenes")
            scenes = detect_scenes(src)
            args.scenes_cache.write_text(json.dumps(scenes))
        print(f"[shorts] {len(scenes)} scenes")
        cands = score_scenes(scenes, rms)

    for c in cands:
        cs, ce, payoff_rel = shape_window(c, rms)
        c["clip_start"] = cs
        c["clip_end"] = ce
        c["payoff_rel"] = payoff_rel

    if args.plan_cache.exists():
        final = json.loads(args.plan_cache.read_text())
        print(f"[shorts] loaded {len(final)} from plan cache")
    else:
        chosen = pick(cands, n=args.n * 3, min_gap=90.0)[: args.n * 2]
        print(f"[shorts] shortlisted {len(chosen)} candidates, transcribing")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for c in chosen:
                cs, ce = c["clip_start"], c["clip_end"]
                segs = transcribe(src, cs, ce, tmp)
                a, b = int(cs), min(int(ce), len(rms))
                clip_rms = rms[a:b] if b > a else np.array([0.0])
                hs, _ = hook_score(segs, clip_rms, cs)
                c["hook_score"] = hs
                c["segs"] = segs
        chosen.sort(key=lambda x: -(x["score"] + 2.0 * x["hook_score"]))
        final = pick(chosen, n=args.n, min_gap=90.0)
        args.plan_cache.write_text(json.dumps(final, indent=2))
        print(f"[shorts] final {len(final)} shorts (cached to {args.plan_cache})")

    results = []

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for i, c in enumerate(final, 1):
            cs, ce = c["clip_start"], c["clip_end"]
            out_mp4 = SHORTS_DIR / f"short-{i:02d}.mp4"
            print(f"[shorts] {i}/{len(final)} {cs:.1f}-{ce:.1f} hook={c.get('hook_score',0):.1f}")
            bb = face_bbox(src, cs, ce, sw, sh, tmp)
            render(src, cs, ce, bb, c.get("segs", []), out_mp4, tmp, sw, sh)
            results.append({
                "index": i,
                "file": str(out_mp4.relative_to(ROOT)),
                "source_start": cs,
                "source_end": ce,
                "duration": ce - cs,
                "payoff_rel": c.get("payoff_rel", 0.0),
                "hook_score": c.get("hook_score", 0.0),
                "rank_score": c.get("score", 0.0),
                "face_bbox": list(bb) if bb else None,
                "transcript": [
                    {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
                    for s in c.get("segs", [])
                ],
            })

    sidecar = {
        "source": str(src),
        "source_duration": dur,
        "source_size": [sw, sh],
        "count": len(results),
        "shorts": results,
    }
    (OUT / "shorts.json").write_text(json.dumps(sidecar, indent=2))
    print(f"[shorts] wrote {OUT / 'shorts.json'}")


if __name__ == "__main__":
    main()
