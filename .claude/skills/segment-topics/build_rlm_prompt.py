#!/usr/bin/env python3
# rlm-assisted segment-topics. Chunks the FULL-resolution transcript into
# ~chunk_sec windows, writes each chunk to a file, and emits an orchestration
# prompt telling the running Claude to dispatch ONE rlm-subcall subagent per
# chunk (so back-half detail of long sources is never compressed away), then
# synthesize a single contiguous topics list AND a list of candidate clip
# moments. Reply schema is a superset of the plain segment-topics schema:
#   {"topics":[...], "candidates":[{quote,t0,t1,why}]}
# parse_reply.py reads topics; parse_candidates.py writes candidates.hint.json.
import json, os, sys

transcript_path, chunk_dir, chunk_sec = sys.argv[1:4]
chunk_sec = float(chunk_sec)
os.makedirs(chunk_dir, exist_ok=True)

tx = json.load(open(transcript_path))
segments = tx.get("segments") or []
if not segments and tx.get("words"):
    cur, t0 = [], None
    for w in tx["words"]:
        if t0 is None:
            t0 = w["t0"]
        cur.append(w["w"])
        if w["t1"] - t0 >= 10:
            segments.append({"t0": t0, "t1": w["t1"], "text": " ".join(cur)})
            cur, t0 = [], None
    if cur:
        segments.append({"t0": t0 or 0, "t1": tx["words"][-1]["t1"], "text": " ".join(cur)})

duration = segments[-1]["t1"] if segments else 0

# group contiguous lines into chunks of up to chunk_sec
chunks = []
cur, start = [], None
for s in segments:
    if start is None:
        start = s["t0"]
    cur.append(s)
    if s["t1"] - start >= chunk_sec:
        chunks.append(cur)
        cur, start = [], None
if cur:
    chunks.append(cur)

manifest = []
for i, ch in enumerate(chunks):
    p = os.path.join(chunk_dir, f"chunk_{i:02d}.txt")
    with open(p, "w") as f:
        for s in ch:
            f.write(f"[{s['t0']:.1f}-{s['t1']:.1f}] {s['text'].strip()}\n")
    manifest.append((p, ch[0]["t0"], ch[-1]["t1"]))

target = max(4, min(60, int(duration / 45) or 4))
listing = "\n".join(
    f"  - {p}   covers [{a:.1f}-{b:.1f}]s" for p, a, b in manifest
)

print(f"""You are running an rlm-style map-reduce to analyze a LONG video transcript
({duration:.1f}s, {len(manifest)} chunks) WITHOUT compressing the back half away.

MAP — dispatch ONE `rlm-subcall` subagent PER chunk file below (use the Task
tool, subagent_type "rlm-subcall"; you may dispatch several in parallel). Give
each subagent this query and tell it to read ONLY its chunk file:

  "This is one window of a longer video transcript; lines are [t0-t1] seconds.
   Return JSON: {{\\"topics\\":[{{\\"t0\\":<float>,\\"t1\\":<float>,\\"title\\":\\"<=8 words\\",
   \\"summary\\":\\"one sentence\\"}}], \\"candidates\\":[{{\\"quote\\":\\"verbatim sentence(s)\\",
   \\"t0\\":<float>,\\"t1\\":<float>,\\"why\\":\\"why it's clip-worthy\\"}}]}}.
   topics = contiguous self-contained subjects in THIS window (one bit/anecdote/
   question/rant each; prefer MORE, SHORTER topics; 20-90s each). candidates =
   the 0-4 most clip-worthy standalone moments in THIS window, with VERBATIM
   quote and REAL timestamps from the lines. Use the ACTUAL second values shown."

Chunk files:
{listing}

REDUCE — merge all subagent results into ONE coherent output for the whole video:
  - topics: CONTIGUOUS, NON-OVERLAPPING, covering [0, {duration:.1f}].
    topics[i].t1 == topics[i+1].t0. Stitch chunk-boundary topics that are the
    same subject; keep distinct ones separate. Aim ~{target} topics total.
    Each topic: t0, t1, title (<=8 words), summary (one sentence).
  - candidates: the strongest standalone clip moments across the WHOLE video
    (dedup near-identical ones). Keep each one's verbatim quote and real t0/t1.

Reply with ONLY a JSON object (no prose, no code fences):
{{"topics": [{{"t0": <float>, "t1": <float>, "title": "<short>", "summary": "<one sentence>"}}],
 "candidates": [{{"quote": "<verbatim>", "t0": <float>, "t1": <float>, "why": "<short>"}}]}}""")
