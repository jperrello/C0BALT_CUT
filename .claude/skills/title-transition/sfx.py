#!/usr/bin/env python3
# synthesize the glitch title SFX bed — the ORIGINAL channel glitch sound:
# panned digital `zap` bursts (sample-and-hold noise) + `crackle`, on the exact
# event schedule the old events.json glitch style emitted. stdlib `wave` only.
# usage: sfx.py <out.wav> <dur> [fps]
import math, os, random, struct, sys, wave

out = sys.argv[1]
dur = float(sys.argv[2])
SR = 48000

# lockstep with styles.py::glitch()
INTRO, OUTT = 0.38, 0.28
MID0 = 1.22

total = dur + 0.3
n = int(total * SR)
L = [0.0] * n
R = [0.0] * n
rng = random.Random(7)   # original seed — reproduces the exact texture


def add(t0, samp, pl=1.0, pr=1.0):
    off = int(t0 * SR)
    for i, s in enumerate(samp):
        j = off + i
        if 0 <= j < n:
            L[j] += s * pl
            R[j] += s * pr


def norm(buf, peak):
    pk = max((abs(x) for x in buf), default=1.0) or 1.0
    return [x / pk * peak for x in buf]


def zap(t, d=0.09):
    f = rng.uniform(300, 1800)
    hold = max(1, int(SR / f))
    m = int(d * SR)
    s, v = [], 0.0
    for i in range(m):
        if i % hold == 0:
            v = rng.uniform(-1, 1)
        s.append(v * (1 - i / m) ** 1.4)
    pan = rng.uniform(0.3, 0.7)
    add(t, norm(s, 0.27), 1 - pan, pan)


def crackle(t, d=0.3):
    m = int(d * SR)
    s = [0.0] * m
    for _ in range(int(d * 70)):
        j = rng.randrange(m)
        for k in range(int(0.002 * SR)):
            if j + k < m:
                s[j + k] += rng.uniform(-1, 1) * (1 - k / (0.002 * SR))
    add(t, norm(s, 0.10))


# the original glitch event schedule — order matters (a shared Random(7) draws
# through the events in this exact sequence, so the texture is reproduced).
zap(0.02)
zap(0.13)
zap(0.25)
crackle(0.0, INTRO)
zap(MID0)
zap(dur - OUTT)
crackle(dur - OUTT, OUTT)

# master gain (TITLE_SFX_GAIN tunes presence; 1.0 = the original level) + the
# original 0.9 ceiling, 16-bit stereo PCM.
gain = float(os.environ.get("TITLE_SFX_GAIN", "1.0")) * 0.9
w = wave.open(out, "w")
w.setnchannels(2)
w.setsampwidth(2)
w.setframerate(SR)
frames = bytearray()
for i in range(n):
    a = max(-1.0, min(1.0, L[i] * gain))
    b = max(-1.0, min(1.0, R[i] * gain))
    frames += struct.pack("<hh", int(a * 32767), int(b * 32767))
w.writeframes(bytes(frames))
w.close()
print(f"sfx: glitch (original zap/crackle) {total:.2f}s -> {out}", file=sys.stderr)
