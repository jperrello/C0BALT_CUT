#!/usr/bin/env python3
# Tier-2 gold-set builder (epic shorts-dwt / shorts-v5i).
# For a source episode that has an OFFICIAL clips channel, recover each clip's real source
# [t0,t1] by aligning the clip's transcript back into the source transcript, weighted by the
# clip's PUBLIC view count. Labels = real editors; weights = real audience. No LLM anywhere.
#
#   build_goldset.py selftest [--work work] [--trials 40]   # validate the aligner, no network
#   build_goldset.py align <source.transcript.json> <clip.transcript.json>
#   build_goldset.py build --source-id ID --source-url URL --clips-url CHANNEL_OR_PLAYLIST_URL
#                          [--out goldset] [--min-conf 0.6] [--max-clips 60]
#
# The aligner is robust to whisper differences between the two transcriptions: it anchors on
# shared token-trigrams and keeps only the longest monotonically-increasing diagonal of anchors
# (LIS), so dropped/substituted/reordered words don't derail it. align_confidence = fraction of
# the clip's trigrams that land on that consistent diagonal; clips below --min-conf are discarded
# and the reject rate is logged.
import argparse, glob, json, os, re, subprocess, sys, tempfile
from bisect import bisect_left

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def norm_tokens(s):
    return [t for t in re.split(r"[^a-z0-9']+", s.lower()) if t]


def words_of(tx_path):
    d = json.load(open(tx_path))
    ws = d.get("words")
    if ws:
        return [(w.get("w", ""), float(w.get("t0", 0)), float(w.get("t1", 0))) for w in ws]
    # fall back to segment text spread evenly (no word times)
    out = []
    for seg in d.get("segments", []):
        toks = norm_tokens(seg.get("text", ""))
        t0, t1 = float(seg.get("t0", 0)), float(seg.get("t1", 0))
        if not toks:
            continue
        step = (t1 - t0) / len(toks)
        for i, t in enumerate(toks):
            out.append((t, t0 + i * step, t0 + (i + 1) * step))
    return out


def grams(tokens, k):
    return [" ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)]


def lis_indices(seq):
    # longest non-decreasing subsequence; returns the chosen positions (indices into seq)
    if not seq:
        return []
    tails, tails_idx, prev = [], [], [-1] * len(seq)
    for i, v in enumerate(seq):
        j = bisect_left(tails, v + 1)  # non-decreasing -> insert point of v+1
        if j == len(tails):
            tails.append(v)
            tails_idx.append(i)
        else:
            tails[j] = v
            tails_idx[j] = i
        prev[i] = tails_idx[j - 1] if j > 0 else -1
    res, k = [], tails_idx[-1]
    while k != -1:
        res.append(k)
        k = prev[k]
    return res[::-1]


def align(source_words, clip_words, k=3):
    # source_words / clip_words: list of (token, t0, t1)
    S = [w[0] for w in source_words]
    C = [w[0] for w in clip_words]
    if len(C) < k or len(S) < k:
        k = max(1, min(2, len(C)))
    sg = grams(S, k)
    cg = grams(C, k)
    pos = {}
    for i, g in enumerate(sg):
        pos.setdefault(g, []).append(i)
    # anchors in clip order: for each clip gram, all source positions. Drop grams that occur
    # too often in the source (non-discriminative "you know that" filler) — they let the chain
    # hop across the whole episode and blow up the recovered envelope.
    MAXFREQ = 6
    anchors = []  # (clip_gram_index, source_gram_index)
    for ci, g in enumerate(cg):
        p = pos.get(g)
        if p and len(p) <= MAXFREQ:
            for si in p:
                anchors.append((ci, si))
    if len(anchors) < 2:
        return None
    # diagonal-offset voting: a contiguous clip aligns at a roughly-constant offset (si - ci).
    # Find the densest offset band, keep its anchors as inliers — robust to duplicate grams and
    # to an editor's internal skips (which just split into a couple of bands; we take the densest).
    band = max(40, int(0.10 * len(cg)) + 5)
    offs = sorted(si - ci for ci, si in anchors)
    best_lo, best_n, j = offs[0], 0, 0
    for i in range(len(offs)):
        while offs[i] - offs[j] > band:
            j += 1
        if i - j + 1 > best_n:
            best_n, best_lo = i - j + 1, offs[j]
    inliers = [(ci, si) for ci, si in anchors if best_lo <= si - ci <= best_lo + band]
    # dedupe to one anchor per clip gram (closest to the band center) and order by clip pos
    bycg = {}
    center = best_lo + band / 2
    for ci, si in inliers:
        if ci not in bycg or abs((si - ci) - center) < abs((bycg[ci] - ci) - center):
            bycg[ci] = si
    picked = sorted(bycg.items())  # (ci, si)
    if len(picked) < 2:
        return None
    ci0, si0 = picked[0]
    ciL, siL = picked[-1]
    # extrapolate the unmatched head/tail along the ~1:1 token diagonal so a clip whose first
    # or last words were dropped/substituted by the second whisper run still recovers its full
    # [t0,t1] envelope (anchors land INSIDE the true span; the clip has ci0 grams before the
    # first match and len(cg)-1-ciL after the last).
    s_start = max(0, si0 - ci0)
    s_end = min(len(source_words) - 1, siL + (len(cg) - 1 - ciL) + k - 1)
    t0 = source_words[s_start][1]
    t1 = source_words[s_end][2]
    conf = len(picked) / max(1, len(cg))
    return {"t0": round(t0, 2), "t1": round(t1, 2), "align_confidence": round(conf, 3),
            "matched_grams": len(picked), "clip_grams": len(cg),
            "span_sec": round(t1 - t0, 2)}


# ---- selftest: validate the aligner on real transcripts (no network) ----
def iou(a0, a1, b0, b1):
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    return inter / union if union > 0 else 0.0


def perturb(tokens, rng, drop=0.12, sub=0.06):
    vocab = list({t for t in tokens}) or ["x"]
    out = []
    for t in tokens:
        r = rng.random()
        if r < drop:
            continue
        if r < drop + sub:
            out.append(vocab[rng.randrange(len(vocab))])
        else:
            out.append(t)
    return out


def selftest(work, trials):
    import random
    paths = sorted(glob.glob(os.path.join(work, "*", "transcript.json")))
    paths = [p for p in paths if words_of(p)]
    if not paths:
        print("SKIP: no work/*/transcript.json with word times", file=sys.stderr)
        return 0
    rng = random.Random(20260626)
    ious, recovered = [], 0
    used = 0
    for _ in range(trials):
        sw = words_of(rng.choice(paths))
        if len(sw) < 200:
            continue
        dur = sw[-1][2]
        a = rng.uniform(0, max(1, dur - 60))
        b = a + rng.uniform(25, 55)
        true = [(w[0], w[1], w[2]) for w in sw if a <= w[1] <= b]
        if len(true) < 25:
            continue
        toks = perturb([w[0] for w in true], rng)
        clip = [(t, 0, 0) for t in toks]  # simulate a separate whisper run: no usable times
        r = align(sw, clip)
        used += 1
        if r:
            ov = iou(r["t0"], r["t1"], true[0][1], true[-1][2])
            ious.append(ov)
            if ov >= 0.5:
                recovered += 1
    if not used:
        print("SKIP: transcripts too short for selftest", file=sys.stderr)
        return 0
    mean_iou = sum(ious) / len(ious) if ious else 0.0
    rate = recovered / used
    print(f"aligner selftest: {used} synthetic clips | IoU>=0.5 recovered {recovered}/{used} "
          f"({rate:.0%}) | mean IoU {mean_iou:.2f} | aligned {len(ious)}/{used}")
    # gate: the riskiest piece must recover the majority before any score is trusted
    ok = rate >= 0.7
    print("PASS" if ok else "FAIL: alignment recovery below 70% — do not trust gold scores",
          file=sys.stderr)
    return 0 if ok else 1


# ---- build: real network path ----
def ytjson(url, flat=False):
    cmd = ["yt-dlp", "-J", "--no-warnings"]
    if flat:
        cmd += ["--flat-playlist"]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return json.loads(out.stdout)


def fetch_audio(url, dest):
    if os.path.isfile(dest):
        return dest
    subprocess.run(["yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "wav",
                    "-o", dest.replace(".wav", ".%(ext)s"), "--no-warnings", url], check=True)
    return dest


def transcribe(media, out_json):
    if os.path.isfile(out_json):
        return out_json
    subprocess.run(["bash", os.path.join(ROOT, ".claude/skills/transcribe/transcribe.sh"),
                    media, out_json], check=True,
                   env={**os.environ})
    return out_json


def build(a):
    cache = os.path.join(a.out, "_cache", a.source_id)
    os.makedirs(cache, exist_ok=True)
    src_tx = os.path.join(cache, "source.transcript.json")
    if not os.path.isfile(src_tx):
        # reuse an already-ingested source transcript if present
        for wd in glob.glob(os.path.join(ROOT, "work", "*")):
            ing = os.path.join(wd, "ingest.json")
            if os.path.isfile(ing):
                try:
                    if json.load(open(ing)).get("url") == a.source_url:
                        if os.path.isfile(os.path.join(wd, "transcript.json")):
                            src_tx = os.path.join(wd, "transcript.json")
                            break
                except Exception:
                    pass
        if not os.path.isfile(src_tx):
            wav = fetch_audio(a.source_url, os.path.join(cache, "source.wav"))
            transcribe(wav, os.path.join(cache, "source.transcript.json"))
            src_tx = os.path.join(cache, "source.transcript.json")
    sw = words_of(src_tx)

    pl = ytjson(a.clips_url, flat=True)
    entries = pl.get("entries", [])[: a.max_clips]
    gold, rejected = [], 0
    for e in entries:
        cu = e.get("url") or f"https://youtu.be/{e.get('id')}"
        try:
            meta = ytjson(cu)
        except RuntimeError:
            rejected += 1
            continue
        views = meta.get("view_count") or 0
        cid = meta.get("id")
        wav = fetch_audio(cu, os.path.join(cache, f"clip_{cid}.wav"))
        ctx = transcribe(wav, os.path.join(cache, f"clip_{cid}.transcript.json"))
        r = align(sw, words_of(ctx))
        if not r or r["align_confidence"] < a.min_conf:
            rejected += 1
            continue
        gold.append({"t0": r["t0"], "t1": r["t1"], "views": views, "clip_url": cu,
                     "clip_title": meta.get("title", ""),
                     "align_confidence": r["align_confidence"], "span_sec": r["span_sec"]})
    os.makedirs(a.out, exist_ok=True)
    dest = os.path.join(a.out, f"{a.source_id}.json")
    json.dump({"source_id": a.source_id, "source_url": a.source_url,
               "clips_url": a.clips_url, "n_aligned": len(gold),
               "n_rejected": rejected,
               "reject_rate": round(rejected / max(1, len(entries)), 3),
               "min_conf": a.min_conf, "gold": sorted(gold, key=lambda g: -g["views"])},
              open(dest, "w"), indent=2)
    print(f"wrote {dest}: {len(gold)} aligned, {rejected} rejected "
          f"({rejected / max(1, len(entries)):.0%} reject rate)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("selftest")
    st.add_argument("--work", default=os.path.join(ROOT, "work"))
    st.add_argument("--trials", type=int, default=40)
    al = sub.add_parser("align")
    al.add_argument("source_tx")
    al.add_argument("clip_tx")
    bu = sub.add_parser("build")
    bu.add_argument("--source-id", required=True)
    bu.add_argument("--source-url", required=True)
    bu.add_argument("--clips-url", required=True)
    bu.add_argument("--out", default=os.path.join(ROOT, "goldset"))
    bu.add_argument("--min-conf", type=float, default=0.6)
    bu.add_argument("--max-clips", type=int, default=60)
    a = ap.parse_args()
    if a.cmd == "selftest":
        return selftest(a.work, a.trials)
    if a.cmd == "align":
        print(json.dumps(align(words_of(a.source_tx), words_of(a.clip_tx)), indent=2))
        return 0
    return build(a)


if __name__ == "__main__":
    sys.exit(main() or 0)
