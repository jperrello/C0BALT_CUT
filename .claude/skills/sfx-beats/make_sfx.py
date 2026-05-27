#!/usr/bin/env python3
# render a full-clip-length stereo WAV with riser+hit+stinger events placed at
# given timestamps. mixed at -18dB under speech (peaks ~0.126).
# args: out.wav total_dur sr plan.json
import json, math, random, struct, sys, wave

out_path, total, sr, plan_path = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
plan = json.load(open(plan_path))

random.seed(13)
n = int(total * sr)
L = [0.0] * n
R = [0.0] * n

PEAK = 0.126  # ~-18 dBFS


def add(buf_off, samp, pan_l=1.0, pan_r=1.0):
    for i, s in enumerate(samp):
        j = buf_off + i
        if 0 <= j < n:
            L[j] += s * pan_l
            R[j] += s * pan_r


def riser(dur):
    m = int(dur * sr)
    out, prev = [], 0.0
    for i in range(m):
        p = i / m
        fc = 250 + 6500 * p  # lowpass cutoff sweeps up
        alpha = 1 - math.exp(-2 * math.pi * fc / sr)
        prev += alpha * (random.uniform(-1, 1) - prev)
        # add a faint pitched sweep underneath for tension
        f = 180 + 1200 * p
        tone = 0.25 * math.sin(2 * math.pi * f * (i / sr))
        env = p ** 1.4
        if p > 0.92:
            env *= max(0.0, (1 - p) / 0.08)  # quick duck at the very end
        out.append((prev + tone) * env)
    pk = max((abs(x) for x in out), default=1.0) or 1.0
    return [x / pk * PEAK for x in out]


def hit():
    m = int(0.22 * sr)
    out = []
    for i in range(m):
        p = i / m
        f = 75 - 25 * p  # 75 -> 50 Hz drop
        s = math.sin(2 * math.pi * f * (i / sr))
        env = math.exp(-p * 6)
        out.append(s * env)
    pk = max((abs(x) for x in out), default=1.0) or 1.0
    return [x / pk * PEAK * 1.1 for x in out]  # hit slightly hotter


def stinger():
    m = int(0.45 * sr)
    out = []
    for i in range(m):
        p = i / m
        # two-tone bell: a fundamental + a fifth, decaying
        s = (math.sin(2 * math.pi * 440 * (i / sr))
             + 0.6 * math.sin(2 * math.pi * 660 * (i / sr)))
        env = math.exp(-p * 4) * (1 - p)
        out.append(s * env)
    pk = max((abs(x) for x in out), default=1.0) or 1.0
    return [x / pk * PEAK * 0.85 for x in out]


if plan.get("ok"):
    r = riser(plan["riser_end"] - plan["riser_start"])
    # pan: riser sweeps L->R
    for i, s in enumerate(r):
        p = i / max(1, len(r))
        j = int(plan["riser_start"] * sr) + i
        if 0 <= j < n:
            L[j] += s * (1.0 - 0.6 * p)
            R[j] += s * (0.4 + 0.6 * p)

    add(int(plan["hit_t"] * sr), hit(), 1.0, 1.0)

st = stinger()
add(int(plan["stinger_t"] * sr), st, 0.85, 0.85)

with wave.open(out_path, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(sr)
    frames = bytearray()
    for i in range(n):
        a = max(-1.0, min(1.0, L[i]))
        b = max(-1.0, min(1.0, R[i]))
        frames += struct.pack("<hh", int(a * 32767), int(b * 32767))
    w.writeframes(bytes(frames))

print(f"sfx-beats: rendered {total:.2f}s sfx bed @ {sr}Hz", file=sys.stderr)
