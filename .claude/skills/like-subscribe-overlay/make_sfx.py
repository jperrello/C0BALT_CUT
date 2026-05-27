#!/usr/bin/env python3
# synthesize a soft "ding" SFX for the like-subscribe CTA. one bell-like
# partial tone on the slide-in, fades out by the slide-out. pure stdlib `wave`.
import math, struct, sys, wave

out = sys.argv[1]
total = float(sys.argv[2])
fly = float(sys.argv[3])
sr = int(sys.argv[4]) if len(sys.argv) > 4 else 44100

n = int(total * sr)
L = [0.0] * n
R = [0.0] * n


def ding(start, dur, f0=880.0, amp=0.35):
    # bell-ish: fundamental + minor third + octave, exponential decay
    s = int(start * sr)
    m = int(dur * sr)
    for i in range(m):
        if s + i >= n:
            break
        t = i / sr
        env = math.exp(-t * 3.0)
        v = (math.sin(2 * math.pi * f0 * t) * 0.55
             + math.sin(2 * math.pi * f0 * 1.19 * t) * 0.30
             + math.sin(2 * math.pi * f0 * 2.0 * t) * 0.18) * env * amp
        L[s + i] += v * 0.9
        R[s + i] += v


# ding on the slide-in landing
ding(start=fly * 0.7, dur=min(1.4, total - fly), f0=988.0, amp=0.34)
# subtle second ding mid-hold so the eye returns to the CTA
ding(start=min(total - fly - 0.3, fly + 1.6), dur=1.0, f0=1318.5, amp=0.18)

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

print(f"like-subscribe-overlay: sfx {total:.2f}s @ {sr}Hz", file=sys.stderr)
