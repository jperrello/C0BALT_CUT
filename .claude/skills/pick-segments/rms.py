#!/usr/bin/env python3
# per-second RMS energy from a media file, JSON to stdout
import json, math, struct, subprocess, sys

src = sys.argv[1]
sr = 8000
proc = subprocess.Popen(
    ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
     "-i", src, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
    stdout=subprocess.PIPE,
)
buckets = []
bytes_per_sec = sr * 2
while True:
    chunk = proc.stdout.read(bytes_per_sec)
    if not chunk:
        break
    n = len(chunk) // 2
    samples = struct.unpack(f"<{n}h", chunk[: n * 2])
    if not samples:
        continue
    s = sum(x * x for x in samples) / n
    rms = math.sqrt(s) / 32768.0
    buckets.append(round(rms, 5))
proc.wait()

if buckets:
    mn, mx = min(buckets), max(buckets)
    avg = sum(buckets) / len(buckets)
else:
    mn = mx = avg = 0.0

json.dump({
    "fps": 1,
    "seconds": len(buckets),
    "min": round(mn, 5),
    "max": round(mx, 5),
    "mean": round(avg, 5),
    "rms": buckets,
}, sys.stdout)
