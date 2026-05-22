#!/usr/bin/env python3
# synthesize the title-transition sound bed: a rising whoosh under the slide-in,
# a soft impact when the card lands, a falling whoosh under the slide-out.
# pure python (filtered noise via a one-pole lowpass), written with stdlib `wave`.
import math, random, struct, sys, wave

out = sys.argv[1]
total = float(sys.argv[2])
fly = float(sys.argv[3])
sr = int(sys.argv[4]) if len(sys.argv) > 4 else 44100

random.seed(7)
n = int(total * sr)
L = [0.0] * n
R = [0.0] * n


def whoosh(rising):
    m = int(fly * sr)
    buf, prev = [], 0.0
    for i in range(m):
        p = i / m
        fc = 300 + 5200 * (p if rising else 1 - p)
        alpha = 1 - math.exp(-2 * math.pi * fc / sr)
        prev += alpha * (random.uniform(-1, 1) - prev)
        if rising:
            env = p ** 1.2
            if p > 0.88:
                env *= max(0.0, (1 - p) / 0.12)
        else:
            env = (1 - p) ** 1.3
            if p < 0.10:
                env *= p / 0.10
        buf.append(prev * env)
    peak = max((abs(x) for x in buf), default=1.0) or 1.0
    return [x / peak * 0.72 for x in buf]


def impact():
    m = int(0.16 * sr)
    return [math.sin(2 * math.pi * (95 - 35 * i / m) * (i / sr))
            * math.exp(-(i / m) * 7) * 0.52 for i in range(m)]


win = whoosh(True)
for i, s in enumerate(win):
    p = i / len(win)
    L[i] += s * (1 - 0.6 * p)
    R[i] += s * (0.4 + 0.6 * p)

base = int(fly * sr)
for i, s in enumerate(impact()):
    if base + i < n:
        L[base + i] += s
        R[base + i] += s

wout = whoosh(False)
base = n - len(wout)
for i, s in enumerate(wout):
    p = i / len(wout)
    if 0 <= base + i < n:
        L[base + i] += s * (0.7 - 0.5 * p)
        R[base + i] += s * (0.7 + 0.3 * p)

with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(sr)
    frames = bytearray()
    for i in range(n):
        a = max(-1.0, min(1.0, L[i]))
        b = max(-1.0, min(1.0, R[i]))
        frames += struct.pack("<hh", int(a * 32767), int(b * 32767))
    w.writeframes(bytes(frames))

print(f"title-transition: sfx {total:.2f}s @ {sr}Hz", file=sys.stderr)
