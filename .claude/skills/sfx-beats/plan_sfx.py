#!/usr/bin/env python3
# decide riser/hit/stinger timestamps for a clip.
# inputs: transcript.json, rms.json (or "-" to skip), total duration seconds.
# output (stdout): JSON {riser_end, hit_t, stinger_t, ok, reason}.
# rules:
#   - riser ends at first pivot word ('but'/'therefore'/'so'/'because'/'however'
#     /'then'/'actually') whose start is within the middle 60% of the clip
#   - hit lands at the highest RMS-per-second peak strictly after the riser end
#   - stinger sits at duration - 0.4s
#   - if no pivot found, return ok=false (skip placement entirely)
import json, sys

tx_path, rms_path, dur_s = sys.argv[1], sys.argv[2], float(sys.argv[3])

tx = json.load(open(tx_path))
words = tx.get("words", [])

PIVOTS = {"but", "therefore", "so", "because", "however", "then", "actually"}
lo, hi = 0.2 * dur_s, 0.8 * dur_s

boundary = None
for w in words:
    tok = w.get("w", "").strip().lower().strip(".,!?;:\"'")
    t0 = float(w.get("t0", 0.0))
    if tok in PIVOTS and lo <= t0 <= hi:
        boundary = t0
        break

stinger_t_default = max(0.0, dur_s - 0.4)

if boundary is None:
    json.dump({
        "ok": False,
        "reason": "no pivot word in middle 60%",
        "stinger_t": round(stinger_t_default, 3),
    }, sys.stdout)
    sys.exit(0)

riser_dur = 0.8
riser_end = boundary
riser_start = max(0.0, riser_end - riser_dur)

hit_t = None
if rms_path != "-":
    rms = json.load(open(rms_path)).get("rms", [])
    # peak strictly after riser end, before stinger
    start_i = int(riser_end) + 1
    end_i = max(start_i, int(dur_s - 0.5))
    window = rms[start_i:end_i]
    if window:
        peak_off = max(range(len(window)), key=lambda i: window[i])
        hit_t = start_i + peak_off + 0.05  # offset slightly into the second
if hit_t is None:
    # fallback: 0.6s after riser
    hit_t = min(dur_s - 0.5, riser_end + 0.6)

stinger_t = max(0.0, dur_s - 0.4)

json.dump({
    "ok": True,
    "riser_start": round(riser_start, 3),
    "riser_end": round(riser_end, 3),
    "hit_t": round(hit_t, 3),
    "stinger_t": round(stinger_t, 3),
    "reason": f"pivot at {boundary:.2f}s",
}, sys.stdout)
