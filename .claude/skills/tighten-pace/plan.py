#!/usr/bin/env python3
import json, os, sys

tx_path = sys.argv[1]
gap_max = float(sys.argv[2])
sentence_beat = float(sys.argv[3])
collapse_to = float(sys.argv[4])
# whisper overshoots the final word's t1 into trailing silence/room-tone; if the clip's
# last shot is a low-motion cutaway that becomes a held/frozen frame, the short reads as
# "ends then hangs". Clamp the final word's tail so the clip lands on the spoken payoff.
max_tail = float(os.environ.get("TIGHTEN_MAX_TAIL", "0.6"))

tx = json.load(open(tx_path))
words = tx.get("words", [])

if words:
    last = words[-1]
    capped = min(last["t1"], last["t0"] + max_tail)
    if capped < last["t1"]:
        last["t1"] = round(capped, 3)

if len(words) < 2:
    json.dump({"keeps": [[words[0]["t0"], words[-1]["t1"]]] if words else [],
               "words": words, "removed_total": 0.0}, sys.stdout)
    sys.exit(0)


def sentence_end(text):
    if not text:
        return False
    t = text.rstrip().rstrip('"\')')
    return t.endswith(('.', '?', '!'))


# Find gaps > gap_max. For each, decide target gap (sentence_beat vs collapse_to).
# Build keep ranges by trimming each side of the long gap so the residual silence
# equals target_gap.
src_end = max(w["t1"] for w in words)
keeps = [[words[0]["t0"], words[0]["t1"]]]
total_removed = 0.0

for i in range(1, len(words)):
    prev = words[i - 1]
    nxt = words[i]
    gap = nxt["t0"] - prev["t1"]
    if gap > gap_max:
        target = sentence_beat if sentence_end(prev.get("w", "")) else collapse_to
        # half on each side, but clamp to actual available gap
        half = min(gap, target) / 2.0
        keeps[-1][1] = prev["t1"] + half
        keeps.append([nxt["t0"] - half, nxt["t1"]])
        total_removed += (gap - min(gap, target))
    else:
        keeps[-1][1] = nxt["t1"]

# build re-timed transcript: each word's new timestamp = original - cumulative_shift
# where cumulative_shift = sum of (gap - target) collapsed before that word.
shifts = []  # per-keep cumulative shift at the keep's start
cum = 0.0
prev_end = None
for a, b in keeps:
    if prev_end is not None:
        cum += (a - prev_end) if (a - prev_end) > 0 else 0.0
        # But our "removed" is actually the gap collapsed below original;
        # the silence we keep (target) is INSIDE the cut zone, so prev_end already
        # accounts for half-pad. The space between prev_end and a is what we drop.
    shifts.append(cum)
    prev_end = b

# assign each word to a keep range
def find_keep(t):
    for ki, (a, b) in enumerate(keeps):
        if a - 1e-6 <= t <= b + 1e-6:
            return ki
    # word falls in a collapsed zone — shouldn't happen since we split AT word boundaries
    # fall back to nearest
    for ki in range(len(keeps) - 1):
        if keeps[ki][1] < t < keeps[ki + 1][0]:
            return ki + 1
    return len(keeps) - 1

new_words = []
for w in words:
    ki = find_keep(w["t0"])
    shift = shifts[ki]
    new_words.append({
        "t0": round(w["t0"] - shift, 3),
        "t1": round(w["t1"] - shift, 3),
        "w": w["w"],
    })

json.dump({
    "keeps": [[round(a, 4), round(b, 4)] for a, b in keeps],
    "words": new_words,
    "removed_total": round(total_removed, 3),
}, sys.stdout)
