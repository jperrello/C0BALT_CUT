#!/usr/bin/env python3
# broll-pick orchestrator. Reads parsed picks, snaps to caption chunks,
# fetches Pexels top-3 per query, runs batch vision verify via claude -p,
# optionally rewrites the query once and retries, then emits broll_plan.json.
import json, os, pathlib, shlex, subprocess, sys, tempfile, urllib.request

picks_path = sys.argv[1]
clip_path = sys.argv[2]
outdir = pathlib.Path(sys.argv[3])
env_path = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None
chunks_path = sys.argv[5] if len(sys.argv) > 5 and sys.argv[5] else None
plan_out = sys.argv[6]

here = pathlib.Path(__file__).parent.resolve()
outdir.mkdir(parents=True, exist_ok=True)

CAP = int(os.environ.get("BROLL_VISION_CAP", "10"))
MIN_DUR = 2.0
MAX_DUR = 5.0

raw = json.load(open(picks_path)).get("picks", [])

chunks = None
if chunks_path and os.path.exists(chunks_path):
    try:
        chunks = json.load(open(chunks_path)).get("chunks", [])
    except Exception:
        chunks = None
        print(f"broll-pick: failed to read chunks at {chunks_path}", file=sys.stderr)
else:
    print("broll-pick: no chunks.json — falling back to raw 2-5s clamp", file=sys.stderr)


def snap_to_chunks(t0, t1, chunks):
    if not chunks:
        d = max(MIN_DUR, min(MAX_DUR, t1 - t0))
        return t0, t0 + d
    # find first chunk whose t1 > t0
    start = None
    for c in chunks:
        if c["t1"] > t0:
            start = c
            break
    if start is None:
        return None
    snap_t0 = start["t0"]
    # accumulate chunks until we exceed original end OR hit 5s ceiling
    snap_t1 = start["t1"]
    for c in chunks:
        if c["t0"] < snap_t0:
            continue
        if c["t0"] >= snap_t1:  # next chunk after current
            if c["t1"] - snap_t0 > MAX_DUR:
                break
            if c["t0"] >= t1 and (snap_t1 - snap_t0) >= MIN_DUR:
                break
            snap_t1 = c["t1"]
        elif c["t1"] > snap_t1:
            snap_t1 = c["t1"]
    # if still under MIN_DUR, extend one more chunk
    if snap_t1 - snap_t0 < MIN_DUR:
        for c in chunks:
            if c["t0"] >= snap_t1:
                if c["t1"] - snap_t0 <= MAX_DUR:
                    snap_t1 = c["t1"]
                break
    if snap_t1 - snap_t0 < MIN_DUR:
        return None
    if snap_t1 - snap_t0 > MAX_DUR:
        # trim to last chunk fully inside MAX_DUR
        keep_t1 = snap_t0 + MAX_DUR
        for c in chunks:
            if c["t0"] < snap_t0:
                continue
            if c["t1"] <= snap_t0 + MAX_DUR:
                snap_t1 = c["t1"]
            else:
                break
        if snap_t1 - snap_t0 < MIN_DUR:
            snap_t1 = snap_t0 + MIN_DUR
    return snap_t0, snap_t1


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def extract_frames(video, t_in_video, want_dur, dest_prefix):
    # 3 frames at start / mid / end of the candidate's first `want_dur` seconds.
    paths = []
    times = [0.1, max(0.1, want_dur / 2), max(0.1, want_dur - 0.1)]
    for i, t in enumerate(times):
        p = f"{dest_prefix}_{i}.jpg"
        r = run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{t:.2f}", "-i", video,
            "-frames:v", "1", "-vf", "scale=320:-2", p,
        ])
        if r.returncode == 0 and os.path.exists(p):
            paths.append(p)
    return paths


def build_strip(per_cand_frames, out_path):
    # per_cand_frames: list of lists of 3 jpg paths. Build grid: N rows x 3 cols.
    rows = []
    for cand in per_cand_frames:
        if len(cand) < 3:
            return False
        row = out_path + f".row{len(rows)}.jpg"
        r = run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", cand[0], "-i", cand[1], "-i", cand[2],
            "-filter_complex", "[0][1][2]hstack=inputs=3",
            row,
        ])
        if r.returncode != 0:
            return False
        rows.append(row)
    if len(rows) == 1:
        os.replace(rows[0], out_path)
        return True
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for row in rows:
        args += ["-i", row]
    args += ["-filter_complex", f"[{']['.join(str(i) for i in range(len(rows)))}]vstack=inputs={len(rows)}", out_path]
    r = run(args)
    return r.returncode == 0


def claude_vision_choose(strip_path, query, n_candidates):
    prompt = f"""You are evaluating Pexels b-roll candidates for the spoken phrase query: "{query}".

The image is a {n_candidates}-row grid. Each row is ONE candidate clip,
showing three frames left-to-right: start, midpoint, end of that clip.

Pick the candidate that best EMBODIES the query as motion / visible scene.
Reject candidates that are off-topic, blank/black, watermarked, marketing
graphics, faces awkwardly cropped, or static when motion is implied.

If NONE of the candidates clearly match the query, return null.

Reply with ONLY a JSON object:
{{"choice": <0-based row index or null>}}

Image: @{strip_path}
"""
    r = run(["claude", "-p", "--output-format", "text"], input=prompt, timeout=120)
    if r.returncode != 0:
        print(f"broll-pick: vision claude -p failed: {r.stderr[:200]}", file=sys.stderr)
        return None
    text = r.stdout
    import re
    m = re.search(r"\{[^{}]*\"choice\"[^{}]*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    c = obj.get("choice")
    if c is None:
        return None
    try:
        ci = int(c)
        if 0 <= ci < n_candidates:
            return ci
    except Exception:
        return None
    return None


def claude_rewrite_query(original, anchor):
    prompt = f"""You are rewriting a Pexels stock-footage search query.
Original query: "{original}"
Anchor word it embodies: "{anchor}"

The original returned no fitting candidates. Rewrite it with a DIFFERENT
angle: if the original was literal, go metaphorical; if abstract, go embodied.
Keep it 4-7 words, describe a concrete visible scene with motion.

Reply with ONLY a JSON object:
{{"query": "<new 4-7 word scene>"}}
"""
    r = run(["claude", "-p", "--output-format", "text"], input=prompt, timeout=60)
    if r.returncode != 0:
        return None
    import re
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        return None
    try:
        return str(json.loads(m.group(0)).get("query", "")).strip() or None
    except Exception:
        return None


def download(link, dest):
    try:
        req = urllib.request.Request(link, headers={"User-Agent": "shorts-broll/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as out:
            while True:
                buf = r.read(1 << 16)
                if not buf: break
                out.write(buf)
        return True
    except Exception as e:
        print(f"broll-pick: download failed: {e}", file=sys.stderr)
        return False


def fetch_candidates(query, want_dur):
    r = run(["python3", str(here / "fetch_pexels.py"), query, f"{want_dur:.2f}"] + ([env_path] if env_path else []))
    try:
        return json.loads(r.stdout).get("candidates", [])
    except Exception:
        return []


def verify_and_pick(query, want_dur, slot_idx, cap_state):
    """Returns (chosen_local_path, used_query, unverified_flag) or (None, None, None)."""
    candidates = fetch_candidates(query, want_dur)
    if not candidates:
        return None, None, None

    # Download all candidates first (so we can frame-strip)
    cand_paths = []
    tmpd = tempfile.mkdtemp(prefix="broll_cand_")
    for ci, c in enumerate(candidates):
        dest = os.path.join(tmpd, f"cand_{ci}.mp4")
        if download(c["link"], dest):
            cand_paths.append(dest)

    if not cand_paths:
        return None, None, None

    # If cap exhausted, take top-1 unverified
    if cap_state["used"] >= CAP:
        if not cap_state.get("first_unverified_logged"):
            print(f"broll-pick: vision cap ({CAP}) exhausted at slot {slot_idx}; taking unverified top-1", file=sys.stderr)
            cap_state["first_unverified_logged"] = True
        dest = outdir / f"broll_{slot_idx:02d}.mp4"
        os.replace(cand_paths[0], dest)
        return str(dest), query, True

    # Build frame strip
    per_cand = []
    for cp in cand_paths:
        frames = extract_frames(cp, 0, want_dur, cp.replace(".mp4", ""))
        if len(frames) >= 3:
            per_cand.append(frames[:3])
    if not per_cand:
        return None, None, None
    strip = os.path.join(tmpd, "strip.jpg")
    if not build_strip(per_cand, strip):
        return None, None, None

    cap_state["used"] += 1
    choice = claude_vision_choose(strip, query, len(per_cand))
    print(f"broll-pick: slot {slot_idx} query={query!r} batch-choice={choice}", file=sys.stderr)
    if choice is not None and choice < len(cand_paths):
        dest = outdir / f"broll_{slot_idx:02d}.mp4"
        os.replace(cand_paths[choice], dest)
        return str(dest), query, False
    return None, None, None


cap_state = {"used": 0}
plan_picks = []
chunks_mtime = None
if chunks_path and os.path.exists(chunks_path):
    chunks_mtime = os.path.getmtime(chunks_path)

for i, p in enumerate(raw):
    t0 = float(p["t0"]); t1 = t0 + float(p["dur"])
    query = p["query"]; anchor = p.get("anchor", "")

    snap = snap_to_chunks(t0, t1, chunks) if chunks else None
    if chunks:
        if not snap:
            print(f"broll-pick: slot {i} dropped (no fitting chunk)", file=sys.stderr)
            continue
        t0, t1 = snap
    want_dur = t1 - t0

    chosen, used_q, unverified = verify_and_pick(query, want_dur, i, cap_state)
    if chosen is None:
        # rewrite fallback (only if cap allows another call)
        if cap_state["used"] < CAP:
            new_q = claude_rewrite_query(query, anchor)
            if new_q and new_q.lower() != query.lower():
                print(f"broll-pick: slot {i} rewrite {query!r} -> {new_q!r}", file=sys.stderr)
                chosen, used_q, unverified = verify_and_pick(new_q, want_dur, i, cap_state)
    if chosen is None:
        print(f"broll-pick: slot {i} DROPPED (no candidate passed)", file=sys.stderr)
        continue

    plan_picks.append({
        "t0": round(t0, 3),
        "t1": round(t1, 3),
        "query": used_q,
        "anchor_word": anchor,
        "clip_path": chosen,
        "unverified": bool(unverified),
    })

with open(plan_out, "w") as f:
    json.dump({
        "picks": plan_picks,
        "vision_calls_used": cap_state["used"],
        "vision_cap": CAP,
        "chunks_mtime": chunks_mtime,
    }, f, indent=2)
print(f"broll-pick: wrote {plan_out} ({len(plan_picks)} picks, {cap_state['used']} vision calls)", file=sys.stderr)
