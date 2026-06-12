#!/usr/bin/env python3
# render a full-length stereo WAV with a short whoosh at each b-roll cut
# boundary. entry whooshes sweep up into the cut, exits sweep down out of it.
# args: out.wav total_dur sr events.json   (events: [{"t": s, "dir": "in"|"out"}])
import json, math, random, struct, sys, wave

out_path, total, sr, ev_path = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
events = json.load(open(ev_path))

random.seed(7)
n = int(total * sr)
L = [0.0] * n
R = [0.0] * n

PEAK = 0.18  # ~-15 dBFS: audible polish, still under speech
DUR = 0.3


def whoosh(up):
    m = int(DUR * sr)
    out, prev = [], 0.0
    for i in range(m):
        p = i / m
        sweep = p if up else 1 - p
        fc = 400 + 5200 * sweep  # bandpass center sweeps with direction
        alpha = 1 - math.exp(-2 * math.pi * fc / sr)
        prev += alpha * (random.uniform(-1, 1) - prev)
        env = math.sin(math.pi * p) ** 1.5  # smooth in/out
        out.append(prev * env)
    pk = max((abs(x) for x in out), default=1.0) or 1.0
    return [x / pk * PEAK for x in out]


for e in events:
    t = float(e["t"])
    up = e.get("dir", "in") == "in"
    # entry whoosh peaks ON the cut; exit whoosh starts on it
    start = t - DUR * 0.7 if up else t - DUR * 0.3
    off = int(start * sr)
    for i, s in enumerate(whoosh(up)):
        j = off + i
        if 0 <= j < n:
            L[j] += s
            R[j] += s

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

print(f"make_whoosh: {len(events)} whoosh(es) over {total:.2f}s", file=sys.stderr)
