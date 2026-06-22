#!/usr/bin/env python3
# rlm-assisted segment-topics — MAP/REDUCE orchestration prompt builder.
#
# The "orchestrator" is the live Claude pane this prompt is fed to: it dispatches
# ONE rlm-subcall subagent per chunk (MAP), verifies + re-dispatches gappy chunks,
# then synthesizes one whole-video result (REDUCE). This module does everything
# deterministic so the agentic part stays small and the parsers always get valid
# input:
#   - seam-aware chunking on natural boundaries (silences / topic-shift cues) with
#     overlap, instead of blind fixed windows (shorts-mk4)
#   - per-chunk MAP cache keyed by content hash, embedded for re-runs (shorts-bui)
#   - per-chunk usage/structure log for batch+model tuning (shorts-t9c)
#   - model routing for the subcall (shorts-j2y)
# The reply schema is a superset of plain segment-topics:
#   {"topics":[...], "candidates":[{quote,t0,t1,why,confidence,thread?,cuts?,kind?,bridge?}]}
# parse_reply.py reads topics; parse_candidates.py writes candidates.hint.json.
import glob, hashlib, json, os, sys

transcript_path, rlm_dir, chunk_sec = sys.argv[1:4]
chunk_sec = float(chunk_sec)

MODEL = os.environ.get("RLM_SUBCALL_MODEL", "sonnet").strip() or "sonnet"
OVERLAP = float(os.environ.get("RLM_SEAM_OVERLAP", "45"))      # window overlap (s)
SEAM_GAP = float(os.environ.get("RLM_SEAM_GAP", "0.6"))        # silence => seam (s)
SEAM_WINDOW = float(os.environ.get("RLM_SEAM_WINDOW", "90"))   # seam search radius (s)
THREADS = os.environ.get("RLM_THREADS", "1") != "0"            # cross-chunk threading
CACHE = os.environ.get("RLM_CACHE", "1") != "0"

chunk_dir = os.path.join(rlm_dir, "chunks")
map_dir = os.path.join(rlm_dir, "map")
os.makedirs(chunk_dir, exist_ok=True)
os.makedirs(map_dir, exist_ok=True)

tx = json.load(open(transcript_path))
segments = tx.get("segments") or []
words = tx.get("words") or []
if not segments and words:
    cur, t0 = [], None
    for w in words:
        if t0 is None:
            t0 = w["t0"]
        cur.append(w["w"])
        if w["t1"] - t0 >= 10:
            segments.append({"t0": t0, "t1": w["t1"], "text": " ".join(cur)})
            cur, t0 = [], None
    if cur:
        segments.append({"t0": t0 or 0, "t1": words[-1]["t1"], "text": " ".join(cur)})

duration = segments[-1]["t1"] if segments else 0
n = len(segments)

# --- seam detection (shorts-mk4) ------------------------------------------
# A "seam" is a segment boundary worth cutting at: a long silence (large inter-
# segment gap) or a topic-shift cue phrase opening the next line. Speaker turns
# aren't available (single-stream whisper), so we lean on silence + cues. Score
# each candidate boundary so chunking can snap to the strongest seam near target.
CUES = (
    "so anyway", "but anyway", "anyway", "moving on", "let me", "let's talk",
    "okay so", "ok so", "alright so", "all right so", "another thing",
    "going back", "as i said", "as i mentioned", "speaking of", "that reminds me",
    "one more thing", "the other thing", "here's the thing", "so the question",
    "changing the subject", "on a different note", "switching gears", "next topic",
)
seam_score = {}
for i in range(1, n):
    gap = segments[i]["t0"] - segments[i - 1]["t1"]
    sc = 0.0
    if gap >= SEAM_GAP:
        sc += min(3.0, gap)
    txt = segments[i]["text"].strip().lower()
    if any(txt.startswith(c) for c in CUES):
        sc += 1.5
    if sc > 0:
        seam_score[i] = sc

# --- seam-aware chunking with overlap -------------------------------------
def boundary_at_or_before(t, lo_idx):
    # last segment index whose t0 <= t, not before lo_idx
    out = lo_idx
    for j in range(lo_idx, n):
        if segments[j]["t0"] <= t:
            out = j
        else:
            break
    return out

ranges = []  # (start_idx, end_idx_exclusive)
start = 0
while start < n:
    start_t = segments[start]["t0"]
    target_idx = None
    for i in range(start, n):
        if segments[i]["t1"] - start_t >= chunk_sec:
            target_idx = i
            break
    if target_idx is None:            # remainder fits in one window
        ranges.append((start, n))
        break
    target_t = segments[target_idx]["t0"]
    best = None
    for idx, sc in seam_score.items():
        if idx <= start or idx >= n:
            continue
        t = segments[idx]["t0"]
        if target_t - SEAM_WINDOW <= t <= target_t + SEAM_WINDOW:
            key = (sc, -abs(t - target_t))
            if best is None or key > best[0]:
                best = (key, idx)
    cut_idx = best[1] if best else target_idx
    cut_idx = max(cut_idx, start + 1)
    ranges.append((start, cut_idx))
    if cut_idx >= n:
        break
    nxt = boundary_at_or_before(segments[cut_idx]["t0"] - OVERLAP, start)
    start = nxt if nxt > start else cut_idx

# --- materialize chunks + cache + usage log -------------------------------
manifest = []
usage = []
embedded = []        # (chunk_id, a, b, cached_json_obj)
to_dispatch = []     # (chunk_id, path, a, b, cache_path)
for ci, (lo, hi) in enumerate(ranges):
    lines = [f"[{segments[s]['t0']:.1f}-{segments[s]['t1']:.1f}] {segments[s]['text'].strip()}"
             for s in range(lo, hi)]
    body = "\n".join(lines)
    a, b = segments[lo]["t0"], segments[hi - 1]["t1"]
    p = os.path.join(chunk_dir, f"chunk_{ci:02d}.txt")
    with open(p, "w") as f:
        f.write(body + "\n")
    h = hashlib.sha1(body.encode("utf-8")).hexdigest()[:8]
    cache_path = os.path.join(map_dir, f"chunk_{ci:02d}.{h}.json")
    nwords = sum(len(segments[s]["text"].split()) for s in range(lo, hi))
    cached_obj = None
    if CACHE and os.path.isfile(cache_path):
        try:
            cached_obj = json.load(open(cache_path))
        except (ValueError, OSError):
            cached_obj = None
    usage.append({
        "chunk": ci, "t0": round(a, 1), "t1": round(b, 1),
        "seconds": round(b - a, 1), "words": nwords, "chars": len(body),
        "est_input_tokens": len(body) // 4, "hash": h,
        "cached": cached_obj is not None, "model": MODEL,
    })
    manifest.append({"chunk": ci, "path": p, "t0": round(a, 1), "t1": round(b, 1),
                     "hash": h, "cache_path": cache_path})
    if cached_obj is not None:
        embedded.append((ci, a, b, cached_obj))
    else:
        to_dispatch.append((ci, p, a, b, cache_path))

# Prune any chunk/cache file that isn't part of THIS chunking — stale-hash files
# (transcript/seam params changed) AND orphans at indices that no longer exist
# (chunk COUNT shrank, e.g. a larger RLM_TOPICS_CHUNK_SEC). Keeps rlm/ clean and
# never reads a result that doesn't match the current windows.
keep_caches = {m["cache_path"] for m in manifest}
keep_chunks = {m["path"] for m in manifest}
for f in glob.glob(os.path.join(map_dir, "chunk_*.json")):
    if f not in keep_caches:
        try:
            os.remove(f)
        except OSError:
            pass
for f in glob.glob(os.path.join(chunk_dir, "chunk_*.txt")):
    if f not in keep_chunks:
        try:
            os.remove(f)
        except OSError:
            pass

json.dump({"source": tx.get("source", ""), "duration": round(duration, 1),
           "chunk_sec": chunk_sec, "overlap": OVERLAP, "n_chunks": len(ranges),
           "model": MODEL, "threads": THREADS,
           "n_cached": len(embedded), "n_dispatch": len(to_dispatch),
           "chunks": usage},
          open(os.path.join(rlm_dir, "usage.json"), "w"), indent=2)
json.dump({"chunks": manifest}, open(os.path.join(rlm_dir, "manifest.json"), "w"), indent=2)

target = max(4, min(60, int(duration / 45) or 4))

# --- subcall query (MAP) ---------------------------------------------------
thread_fields = ""
if THREADS:
    thread_fields = (
        ',\n   "open_threads":[{"t0":<float>,"t1":<float>,"quote":"<verbatim>",'
        '"note":"a setup/question/claim raised HERE that is NOT resolved in this window"}],\n'
        '   "callbacks":[{"t0":<float>,"t1":<float>,"quote":"<verbatim>",'
        '"refers_to":"what earlier point this calls back to (\'as I said earlier\', \'going back to\')"}]'
    )
thread_query_note = ""
if THREADS:
    thread_query_note = (
        "\n   open_threads = setups/questions/claims this window OPENS but does NOT resolve "
        "(they pay off later in the video). callbacks = explicit references to something said "
        "EARLIER ('as I said', 'going back to', 'remember when'). Both are cheap to note and "
        "let the reduce stitch distant setup->payoff threads — list any you notice, else []."
    )

query = (
    'This is one window of a longer video transcript; lines are [t0-t1] seconds.\n'
    '   Return JSON: {"topics":[{"t0":<float>,"t1":<float>,"title":"<=8 words",'
    '"summary":"one sentence"}],\n'
    '   "candidates":[{"quote":"verbatim sentence(s)","t0":<float>,"t1":<float>,'
    '"why":"why it is clip-worthy","confidence":<0.0-1.0>}]' + thread_fields + '}.\n'
    '   topics = contiguous self-contained subjects in THIS window (one bit/anecdote/\n'
    '   question/rant each; prefer MORE, SHORTER topics; 20-90s each) and they MUST\n'
    '   TILE the whole window with no gaps. candidates = the 0-4 most clip-worthy\n'
    '   standalone moments in THIS window, VERBATIM quote, REAL timestamps from the\n'
    '   lines, and confidence = how truly STANDALONE/clip-worthy it is for a cold\n'
    '   viewer (1.0 = complete self-contained arc; <0.5 = needs surrounding context).'
    + thread_query_note +
    '\n   Use the ACTUAL second values shown.'
)

# chunk listing for dispatch
disp_lines = []
for ci, p, a, b, cp in to_dispatch:
    disp_lines.append(f"  - chunk {ci:02d}: {p}   covers [{a:.1f}-{b:.1f}]s"
                      f"   -> WRITE result to {cp}")
disp_block = "\n".join(disp_lines) if disp_lines else "  (none — all chunks served from cache)"

# embedded cached results for reduce
cache_block = ""
if embedded:
    rows = []
    for ci, a, b, obj in embedded:
        rows.append(f"  chunk {ci:02d} [{a:.1f}-{b:.1f}]s: " + json.dumps(obj, separators=(",", ":")))
    cache_block = (
        "\nPRE-COMPUTED chunk results (cached from a prior run — use these AS-IS in the "
        "REDUCE, do NOT re-dispatch them):\n" + "\n".join(rows) + "\n"
    )

thread_reduce = ""
if THREADS:
    thread_reduce = """
  - THREADING (cross-chunk): scan ALL candidates + open_threads + callbacks across the
    WHOLE video for genuine NARRATIVE THREADS whose pieces sit far apart — a setup in one
    place that pays off elsewhere, a callback to an earlier point, an escalation, or a
    contradiction later resolved. When the link is real and would make ONE compelling
    standalone short, emit a COMPOUND candidate:
      {"thread": true, "kind": "setup_payoff|callback|escalation|contradiction",
       "cuts": [[t0,t1],[t0,t1]], "bridge": "<one sentence: the conceptual link>",
       "quote": "<the payoff line, verbatim>", "why": "<why it works as a short>",
       "confidence": <0.0-1.0>}
    Rules: cuts are 2-3 ordered, source-chronological, non-overlapping ranges; total 20-55s;
    ONLY emit a thread when the connection is real (not a loose theme match). Most videos
    yield 0-2 real threads — emit none rather than force one."""

reduce_schema = (
    '{"topics": [{"t0": <float>, "t1": <float>, "title": "<short>", "summary": "<one sentence>"}],\n'
    ' "candidates": [{"quote": "<verbatim>", "t0": <float>, "t1": <float>, "why": "<short>", '
    '"confidence": <0.0-1.0>'
)
if THREADS:
    reduce_schema += ', "thread": <true only for cross-chunk stitches>, '
    reduce_schema += '"kind": "<setup_payoff|callback|escalation|contradiction, threads only>", '
    reduce_schema += '"cuts": [[<float>,<float>],[<float>,<float>]] (threads need >=2 cuts), "bridge": "<threads only>"'
reduce_schema += "}]}"

print(f"""You are running an rlm-style map-reduce to analyze a LONG video transcript
({duration:.1f}s, {len(ranges)} chunks) WITHOUT compressing the back half away.
Chunks were cut on natural seams (silences / topic-shift cues) and OVERLAP by
~{OVERLAP:.0f}s, so a moment that straddles a boundary appears whole in one window.

MAP — dispatch ONE `rlm-segment-subcall` subagent per chunk listed below (use the Task tool,
subagent_type "rlm-segment-subcall" EXACTLY [NOT the generic "rlm-subcall"], model "{MODEL}";
dispatch several in parallel). Give each subagent this query and tell it to read ONLY its chunk
file. As EACH subagent returns, YOU (the orchestrator) WRITE its raw JSON to that chunk's cache
path shown beside it — the subagent is read-only and cannot write — so a re-run skips it:

  "{query}"

Chunks to dispatch:
{disp_block}
{cache_block}
VERIFY (before reducing) — for EACH chunk result (dispatched or cached) confirm: it is
valid JSON, and its `topics` actually TILE its [t0,t1] window (cover it, roughly
contiguous, no large hole). If a chunk came back empty, garbled/unparseable, or left a
big gap, RE-DISPATCH that ONE chunk once more (same query, model "{MODEL}") and use the
retry. After a FRESH dispatch, WRITE that subagent's raw JSON to the chunk's cache path
shown above (so a re-run skips it). Do not re-dispatch cached chunks.

REDUCE — merge all chunk results into ONE coherent output for the whole video:
  - topics: CONTIGUOUS, NON-OVERLAPPING, covering [0, {duration:.1f}].
    topics[i].t1 == topics[i+1].t0. Stitch chunk-boundary topics that are the same
    subject; keep distinct ones separate. Because windows overlap, DEDUP topics/candidates
    that the overlap reported twice (same moment, near-identical timestamps). Aim
    ~{target} topics total. Each topic: t0, t1, title (<=8 words), summary (one sentence).
  - candidates: the strongest standalone clip moments across the WHOLE video, each with
    its verbatim quote, real t0/t1, and a confidence 0.0-1.0 (how truly standalone it is).{thread_reduce}

Reply with ONLY a JSON object (no prose, no code fences):
{reduce_schema}""")
