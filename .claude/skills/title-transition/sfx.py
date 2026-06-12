#!/usr/bin/env python3
# synthesize the SFX bed for one title style from its events.json. stdlib only.
# usage: sfx.py <events.json> <out.wav>
import json, math, random, struct, sys, wave

ev = json.load(open(sys.argv[1]))
out = sys.argv[2]
SR = 48000
total = ev["dur"] + 1.2
n = int(total * SR)
L = [0.0] * n
R = [0.0] * n
rng = random.Random(7)


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


def sweep(f0, f1, d, shape=1.0):
    m = int(d * SR)
    ph, out_ = 0.0, []
    for i in range(m):
        p = i / m
        f = f0 + (f1 - f0) * (p ** shape)
        ph += 2 * math.pi * f / SR
        out_.append(math.sin(ph))
    return out_


def lpnoise(d, c0, c1, shape=1.0):
    m = int(d * SR)
    prev, out_ = 0.0, []
    for i in range(m):
        p = i / m
        fc = c0 + (c1 - c0) * (p ** shape)
        alpha = 1 - math.exp(-2 * math.pi * fc / SR)
        prev += alpha * (rng.uniform(-1, 1) - prev)
        out_.append(prev)
    return out_


def riser(e):
    d = e.get("dur", 0.3)
    body = lpnoise(d, 300, 7000)
    tone = sweep(160, 1100, d)
    m = len(body)
    s = [(body[i] * 1.0 + tone[i] * 0.3) * ((i / m) ** 1.7) for i in range(m)]
    add(e["t"], norm(s, 0.34))


def boom(e):
    d = 0.9
    body = sweep(82, 40, d, 0.5)
    sub = sweep(36, 30, d, 0.5)
    m = len(body)
    s = []
    for i in range(m):
        p = i / m
        env = math.exp(-p * 4.5)
        s.append(body[i] * env + sub[i] * 0.5 * math.exp(-p * 3))
    for i in range(int(0.012 * SR)):
        s[i] += rng.uniform(-1, 1) * (1 - i / (0.012 * SR)) * 0.8
    add(e["t"], norm(s, 0.52))


def key(e):
    m = int(0.014 * SR)
    s, prev = [], 0.0
    for i in range(m):
        v = rng.uniform(-1, 1)
        s.append((v - prev) * math.exp(-(i / m) * 7))
        prev = v
    pan = rng.uniform(0.35, 0.65)
    add(e["t"], norm(s, 0.20 * rng.uniform(0.8, 1.15)), 1 - pan, pan)


def ding(e):
    d = 0.4
    m = int(d * SR)
    s = []
    for i in range(m):
        p = i / m
        t = i / SR
        v = math.sin(2 * math.pi * 1244.5 * t) + 0.45 * math.sin(2 * math.pi * 2489 * t)
        s.append(v * math.exp(-p * 6))
    add(e["t"], norm(s, 0.16))


def zap(e):
    d = e.get("dur", 0.09)
    f = rng.uniform(300, 1800)
    hold = max(1, int(SR / f))
    m = int(d * SR)
    s, v = [], 0.0
    for i in range(m):
        if i % hold == 0:
            v = rng.uniform(-1, 1)
        s.append(v * (1 - i / m) ** 1.4)
    pan = rng.uniform(0.3, 0.7)
    add(e["t"], norm(s, 0.27), 1 - pan, pan)


def crackle(e):
    d = e.get("dur", 0.3)
    m = int(d * SR)
    s = [0.0] * m
    for _ in range(int(d * 70)):
        j = rng.randrange(m)
        for k in range(int(0.002 * SR)):
            if j + k < m:
                s[j + k] += rng.uniform(-1, 1) * (1 - k / (0.002 * SR))
    add(e["t"], norm(s, 0.10))


def pop(e):
    f0 = e.get("pitch", 500)
    d = 0.07
    body = sweep(f0, f0 * 2.3, d)
    m = len(body)
    s = [body[i] * math.sin(math.pi * i / m) for i in range(m)]
    pan = 0.35 + 0.3 * rng.random()
    add(e["t"], norm(s, 0.30), 1 - pan, pan)


def boing(e):
    d = 0.55
    m = int(d * SR)
    ph, s = 0.0, []
    for i in range(m):
        p = i / m
        t = i / SR
        f = 330 * (2 ** (-p * 1.3)) * (1 + 0.07 * math.sin(2 * math.pi * 26 * t))
        ph += 2 * math.pi * f / SR
        s.append(math.sin(ph) * math.exp(-p * 4.5))
    add(e["t"], norm(s, 0.28))


def whoosh(e):
    d = e.get("dur", 0.3)
    up = e.get("up", 1)
    body = lpnoise(d, 350 if up else 5200, 5200 if up else 350)
    m = len(body)
    if up:
        s = [body[i] * ((i / m) ** 1.5) for i in range(m)]
    else:
        s = [body[i] * math.sin(math.pi * i / m) for i in range(m)]
    add(e["t"], norm(s, 0.30))


def ident(e):
    for k, f in enumerate((659.3, 880.0, 987.8)):
        d = 0.55
        m = int(d * SR)
        s = []
        for i in range(m):
            p = i / m
            t = i / SR
            v = math.sin(2 * math.pi * f * t) + 0.35 * math.sin(2 * math.pi * f * 2 * t)
            s.append(v * math.exp(-p * 3.5))
        pan = 0.5 + (k - 1) * 0.12
        add(e["t"] + k * 0.095, norm(s, 0.19), 1 - pan, pan)


def swell(e):
    d = e.get("dur", 1.1)
    body = lpnoise(d, 400, 2300)
    pad = sweep(92, 92, d)
    m = len(body)
    s = []
    for i in range(m):
        p = i / m
        env = (p ** 2.2) * (1.0 if p < 0.95 else (1 - p) / 0.05)
        s.append((body[i] * 0.8 + pad[i] * 0.35) * env)
    add(e["t"], norm(s, 0.22))


def thump(e):
    d = 0.8
    m = int(d * SR)
    s = []
    for i in range(m):
        p = i / m
        t = i / SR
        atk = min(1.0, i / (0.005 * SR))
        s.append(math.sin(2 * math.pi * 49 * t) * math.exp(-p * 3.2) * atk)
    add(e["t"], norm(s, 0.46))


SYNTH = {"riser": riser, "boom": boom, "key": key, "ding": ding, "zap": zap,
         "crackle": crackle, "pop": pop, "boing": boing, "whoosh": whoosh,
         "ident": ident, "swell": swell, "thump": thump}

for e in ev["events"]:
    SYNTH[e["kind"]](e)

with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    frames = bytearray()
    for i in range(n):
        a = max(-1.0, min(1.0, L[i] * 0.9))
        b = max(-1.0, min(1.0, R[i] * 0.9))
        frames += struct.pack("<hh", int(a * 32767), int(b * 32767))
    w.writeframes(bytes(frames))

print(f"sfx: {ev['style']} {total:.2f}s {len(ev['events'])} events", file=sys.stderr)
