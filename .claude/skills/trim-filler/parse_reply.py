#!/usr/bin/env python3
import json, sys, re

reply_path = sys.argv[1]
tx_path    = sys.argv[2]
pad        = float(sys.argv[3])

reply = open(reply_path).read().strip()
tx    = json.load(open(tx_path))
words = tx.get("words", [])
n     = len(words)

input_dur = (words[-1]["t1"] - words[0]["t0"]) if words else 0.0

m = re.search(r"\{.*\}", reply, re.DOTALL)
if not m:
    print(f"parse_reply: no JSON object in reply: {reply[:400]}", file=sys.stderr)
    sys.exit(1)
data = json.loads(m.group(0))

remove_ranges = data.get("remove", [])
removed_set = set()
removed_meta = []
for r in remove_ranges:
    if not (isinstance(r, list) and len(r) == 2):
        continue
    a, b = int(r[0]), int(r[1])
    a = max(0, min(n - 1, a))
    b = max(0, min(n - 1, b))
    if b < a:
        a, b = b, a
    txt = " ".join(words[i]["w"] for i in range(a, b + 1))
    removed_meta.append({
        "t0": round(words[a]["t0"], 3),
        "t1": round(words[b]["t1"], 3),
        "words": txt,
    })
    for i in range(a, b + 1):
        removed_set.add(i)

kept_idx = [i for i in range(n) if i not in removed_set]

if not kept_idx:
    out_keeps = {
        "source": tx_path,
        "keeps": [],
        "removed": removed_meta,
        "removed_total": 0.0,
        "notes": data.get("notes", ""),
    }
    out_tx = {"source": tx.get("source", ""), "language": tx.get("language", "en"), "words": []}
    json.dump({"keeps": out_keeps, "transcript": out_tx}, sys.stdout)
    sys.exit(0)

# group contiguous kept indices into spans
spans = []
cur = [kept_idx[0], kept_idx[0]]
for i in kept_idx[1:]:
    if i == cur[1] + 1:
        cur[1] = i
    else:
        spans.append(cur)
        cur = [i, i]
spans.append(cur)

# build padded keep ranges in original time
keeps = []
for a, b in spans:
    t0 = max(0.0, words[a]["t0"] - pad)
    t1 = words[b]["t1"] + pad
    keeps.append([t0, t1])

# Hard ceiling: kept duration must not exceed input duration.
# If it does (parser/merge bug), fall back to no-op pass-through and log.
kept_sum = sum(b - a for a, b in keeps)
if input_dur > 0 and kept_sum > input_dur + 1e-3:
    print(f"trim-filler: WARN sum(keeps)={kept_sum:.2f}s > input_dur={input_dur:.2f}s — falling back to no-op", file=sys.stderr)
    out_keeps = {
        "source": tx_path,
        "keeps": [[round(words[0]["t0"], 3), round(words[-1]["t1"], 3)]],
        "removed": [],
        "removed_total": 0.0,
        "notes": "fallback: kept ranges exceeded input duration",
    }
    json.dump({"keeps": out_keeps, "transcript": tx}, sys.stdout)
    sys.exit(0)

# Warn if more than 40% of input duration was removed (suspicious pick).
removed_dur = max(0.0, input_dur - kept_sum)
if input_dur > 0 and removed_dur / input_dur > 0.40:
    print(f"trim-filler: WARN removed {removed_dur:.1f}s / {input_dur:.1f}s ({removed_dur/input_dur*100:.0f}%) — investigate pick-segments", file=sys.stderr)

# merge overlaps after padding (and remember which spans collapsed)
merged = [list(keeps[0])]
merge_map = [0]
for i in range(1, len(keeps)):
    if keeps[i][0] <= merged[-1][1]:
        merged[-1][1] = max(merged[-1][1], keeps[i][1])
        merge_map.append(len(merged) - 1)
    else:
        merged.append(list(keeps[i]))
        merge_map.append(len(merged) - 1)

# compute cumulative removed time at start of each kept range
shifts = []
removed_time = 0.0
prev_end = 0.0
for a, b in merged:
    removed_time += (a - prev_end)
    shifts.append(removed_time)
    prev_end = b

# trailing removed time after last kept range — add it for reporting
src_end = max((w["t1"] for w in words), default=0.0)
trailing = max(0.0, src_end - prev_end)

# new word list with shifted timestamps
new_words = []
for span_idx, (a, b) in enumerate(spans):
    shift = shifts[merge_map[span_idx]]
    for i in range(a, b + 1):
        w = words[i]
        new_words.append({
            "t0": round(w["t0"] - shift, 3),
            "t1": round(w["t1"] - shift, 3),
            "w": w["w"],
        })

out_keeps = {
    "source": tx_path,
    "keeps": [[round(a, 3), round(b, 3)] for a, b in merged],
    "removed": removed_meta,
    "removed_total": round(removed_time + trailing, 3),
    "notes": data.get("notes", ""),
}
out_tx = {
    "source": tx.get("source", ""),
    "language": tx.get("language", "en"),
    "words": new_words,
}
json.dump({"keeps": out_keeps, "transcript": out_tx}, sys.stdout)
