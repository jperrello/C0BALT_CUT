#!/usr/bin/env python3
# synthesize the glitch title SFX bed. stdlib `wave` only — no assets. synced to
# styles.py's glitch timing: an intro data-corruption zap as the banner
# materializes (0..intro), a short scanline-tear stutter at the mid burst
# (mid0..mid1), and a reverse-zap dissolve on the outro (dur-outt..dur).
# usage: sfx.py <out.wav> <dur> [fps]
import math, random, struct, sys, wave

out = sys.argv[1]
dur = float(sys.argv[2])
SR = 48000

# keep these in lockstep with styles.py::glitch()
INTRO, OUTT = 0.38, 0.28
MID0, MID1 = 1.22, 1.36

total = dur + 0.15
n = int(total * SR)
buf = [0.0] * n
rng = random.Random(99)  # same seed family as the visual for a matched feel


def add(t0, samp, gain=1.0):
    off = int(t0 * SR)
    for i, s in enumerate(samp):
        j = off + i
        if 0 <= j < n:
            buf[j] += s * gain


def norm(s, peak):
    pk = max((abs(x) for x in s), default=1.0) or 1.0
    return [x / pk * peak for x in s]


def sweep(f0, f1, d, shape=1.0):
    m = int(d * SR)
    ph, o = 0.0, []
    for i in range(m):
        f = f0 + (f1 - f0) * ((i / m) ** shape)
        ph += 2 * math.pi * f / SR
        o.append(1.0 if math.sin(ph) >= 0 else -1.0)  # square = harsh/digital
    return o


# sample-and-hold noise (a bit-crushed data-corruption texture)
def crush(d, rate, cut=0.0):
    m = int(d * SR)
    hold = max(1, int(SR / rate))
    o, cur = [], 0.0
    for i in range(m):
        if i % hold == 0:
            cur = rng.uniform(-1, 1)
            if cut and rng.random() < cut:
                cur = 0.0
        o.append(cur)
    return o


# hard on/off gate — the audio analogue of the scanline tear
def stutter(sig, chunks):
    m = len(sig)
    seg = max(1, m // chunks)
    o = list(sig)
    for c in range(chunks):
        if rng.random() < 0.4:
            for i in range(c * seg, min(m, (c + 1) * seg)):
                o[i] = 0.0
    return o


def zap(d, f0, f1, peak):
    body = sweep(f0, f1, d, 1.4)
    grit = crush(d, 5200, cut=0.25)
    m = len(body)
    s = [(body[i] * 0.7 + grit[i] * 0.5) * math.exp(-(i / m) * 3.2) for i in range(m)]
    return norm(s, peak)


# --- intro: banner slams in with a digital zap + corruption stutter ---
z = zap(INTRO, 1400, 180, 0.5)
add(0.0, stutter(z, 9))
tear = norm(stutter(crush(INTRO * 0.7, 3400, cut=0.3), 12), 0.28)
add(0.02, tear)

# --- mid burst: brief scanline-tear stutter ---
mb = norm(stutter(crush(MID1 - MID0, 4200, cut=0.35), 7), 0.3)
add(MID0, mb)
add(MID0, norm(sweep(900, 500, MID1 - MID0), 0.14))

# --- outro: reverse zap dissolves the banner ---
o = zap(OUTT, 220, 1300, 0.34)
o = o[::-1]  # reverse so it swells then cuts (dissolve feel)
add(dur - OUTT, stutter(o, 6))

# soft limiter + 16-bit PCM
pk = max((abs(x) for x in buf), default=1.0) or 1.0
if pk > 0.97:
    buf = [x / pk * 0.97 for x in buf]

w = wave.open(out, "w")
w.setnchannels(1)
w.setsampwidth(2)
w.setframerate(SR)
w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, x)) * 32767)) for x in buf))
w.close()
print(f"sfx: glitch bed {total:.2f}s -> {out}", file=sys.stderr)
