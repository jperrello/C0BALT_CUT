#!/usr/bin/env python3
# pick-speaker: per transcript segment, pick the active-speaker face box.
# Deterministic dominant-face heuristic: cluster face boxes in the segment
# window, score clusters by persistence x size, pick the winner.
import json, sys, argparse


def center(b):
    return (b["x"] + b["w"] / 2.0, b["y"] + b["h"] / 2.0)


def cluster(boxes):
    # Greedy spatial clustering by center proximity.
    clusters = []
    for b in boxes:
        cx, cy = center(b)
        placed = False
        for c in clusters:
            ccx, ccy = c["cx"], c["cy"]
            ref = max(b["w"], b["h"], c["members"][0]["w"]) * 0.6
            if abs(cx - ccx) <= ref and abs(cy - ccy) <= ref:
                c["members"].append(b)
                c["cx"] = sum(center(m)[0] for m in c["members"]) / len(c["members"])
                c["cy"] = sum(center(m)[1] for m in c["members"]) / len(c["members"])
                placed = True
                break
        if not placed:
            clusters.append({"cx": cx, "cy": cy, "members": [b]})
    return clusters


def mean_box(boxes):
    n = len(boxes)
    return {
        "x": round(sum(b["x"] for b in boxes) / n),
        "y": round(sum(b["y"] for b in boxes) / n),
        "w": round(sum(b["w"] for b in boxes) / n),
        "h": round(sum(b["h"] for b in boxes) / n),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("faces")
    ap.add_argument("video", nargs="?", default="")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tx = json.load(open(args.transcript))
    fc = json.load(open(args.faces))
    out_path = args.out or (args.video or args.transcript) + ".speaker.json"

    frames = fc.get("frames", [])
    segments = tx.get("segments", [])

    spans = []
    for seg in segments:
        t0, t1 = seg["t0"], seg["t1"]
        boxes = [b for fr in frames if t0 <= fr["t"] <= t1 for b in fr.get("boxes", [])]
        n_frames = max(1, sum(1 for fr in frames if t0 <= fr["t"] <= t1))

        if not boxes:
            spans.append({"t0": t0, "t1": t1, "speaker_box": None, "confidence": "none"})
            continue

        clusters = cluster(boxes)
        clusters.sort(
            key=lambda c: len(c["members"]) * (sum(m["w"] * m["h"] for m in c["members"]) / len(c["members"])) ** 0.5,
            reverse=True,
        )
        best = clusters[0]
        coverage = len(best["members"]) / n_frames

        if len(clusters) == 1:
            conf = "high" if coverage >= 0.5 else "medium"
        elif coverage >= 0.6:
            conf = "medium"
        else:
            conf = "low"

        spans.append({
            "t0": t0,
            "t1": t1,
            "speaker_box": mean_box(best["members"]),
            "confidence": conf,
        })

    # Smooth: low/none spans inherit the nearest confident neighbour's box.
    last = None
    for s in spans:
        if s["speaker_box"] and s["confidence"] in ("high", "medium"):
            last = s["speaker_box"]
        elif s["speaker_box"] is None and last:
            s["speaker_box"] = dict(last)
    nxt = None
    for s in reversed(spans):
        if s["speaker_box"] and s["confidence"] in ("high", "medium"):
            nxt = s["speaker_box"]
        elif s["speaker_box"] is None and nxt:
            s["speaker_box"] = dict(nxt)

    with open(out_path, "w") as f:
        json.dump({"source": tx.get("source", ""), "spans": spans}, f, indent=2)

    named = sum(1 for s in spans if s["speaker_box"])
    print(f"pick-speaker: wrote {out_path} ({len(spans)} spans, {named} with a box)", file=sys.stderr)
    print(out_path)


if __name__ == "__main__":
    main()
