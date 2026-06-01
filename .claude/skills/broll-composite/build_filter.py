#!/usr/bin/env python3
# Emit an ffmpeg filter_complex that hard-cuts each verified b-roll pick over the
# base 1080x1920 clip. Each b-roll input is scale-to-cover + center-crop to
# 1080x1920, time-shifted to its window start, gated by enable=between(t,t0,t1).
# argv: plan.json  -> prints "<filter>;<n_inputs>" with valid picks count.
import json, sys, os

plan = json.load(open(sys.argv[1]))
W, H = 1080, 1920
picks = [p for p in plan.get("picks", [])
         if p.get("clip_path") and os.path.exists(p["clip_path"])]
picks.sort(key=lambda p: p["t0"])

if not picks:
    print("|0")
    sys.exit(0)

parts = []
# input 0 is the base clip; b-roll inputs are 1..n
for i, p in enumerate(picks):
    idx = i + 1
    t0 = float(p["t0"])
    parts.append(
        f"[{idx}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},setsar=1,setpts=PTS-STARTPTS+{t0}/TB[bv{idx}]"
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
