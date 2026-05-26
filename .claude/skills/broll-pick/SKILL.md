---
name: broll-pick
description: Claude-driven Pexels b-roll candidate selection with batch vision verification. Reads the clip transcript (and optional chunks.json), picks anchor-word slots, fetches the top 3 Pexels candidates per query, builds a 3-frame-per-candidate grid strip, asks Claude to choose the best index or "none." On "none" it rewrites the query once (literal->metaphorical or abstract->embodied) and retries; on a second miss the slot is dropped. Emits broll_plan.json — {t0,t1,query,clip_path,anchor_word} entries. No video output. Pair with broll-composite to render.
allowed-tools: Bash
user-invocable: true
---

# broll-pick

The picking half of the split-out broll skill. Owns everything Claude-driven:
anchor detection, Pexels search, batch vision verify, query rewrite, download.
The output is `broll_plan.json` — a JSON manifest that `broll-composite` can
overlay onto the finished short with pure ffmpeg.

## Invoke

```
.claude/skills/broll-pick/broll-pick.sh <input> <transcript.json> <broll_plan.json> [ingest.json] [chunks.json]
```

- `input`: the finished pre-broll clip (post-loudnorm in the canonical chain).
  Needed only for ffprobe duration; not re-encoded here.
- `transcript.json`: clip-local word-timed transcript (the rebased / trimmed one).
- `broll_plan.json`: output manifest path.
- `ingest.json` (optional): source video metadata for topical context.
- `chunks.json` (optional): the `chunk-captions` output for this clip. When
  provided, each slot's `[t0, t1]` snaps to whole chunk boundaries (max 5s,
  min 2s). Without it the skill falls back to a 2-5s clamp (logged to stderr).

## Output

`broll_plan.json`:

```json
{
  "picks": [
    {"t0": 4.31, "t1": 7.15, "query": "feet running on pavement",
     "anchor_word": "ran", "clip_path": "/abs/path/to/broll_00.mp4",
     "unverified": false}
  ],
  "vision_calls_used": 4,
  "vision_cap": 10,
  "chunks_mtime": 1746000000.0
}
```

Downloaded Pexels clips are stored alongside `broll_plan.json` under
`<plan_dir>/broll_<plan_basename>/broll_NN.mp4`. Re-running the skill with
unchanged inputs is a cache hit via `<plan>.pickmeta` (keyed on input +
transcript + chunks mtimes).

## How

1. `build_prompt.py` formats the transcript word-by-word and asks Claude
   (`claude -p`) to apply the anchor-word model: NOUN/VERB/EMOTION/PIVOT tag,
   open a slot per anchor, drop slots <2s.
2. `parse_reply.py` enforces in-bounds and non-overlap, drops slots <2s.
3. `plan.py` orchestrates the per-slot work:
   - Snap `[t0, t1]` to `chunks.json` boundaries (when provided). A slot
     covers one or more whole chunks, never enters or exits mid-word. Max 5s
     coverage; if a chunk is <2s, extend forward one chunk; if still <2s,
     drop.
   - `fetch_pexels.py` returns the top 3 landscape mp4 candidates per query
     (smallest with width>=640, duration>=want_dur).
   - Download each candidate, extract 3 frames per candidate
     (start/mid/end), build an N-row hstacked grid, ask Claude via `claude -p`
     for `{"choice": <row index or null>}`.
   - On `null`: call Claude text-only for a rewritten query (literal ->
     metaphorical OR abstract -> embodied), pull top 3 again, batch-check
     again. On a second `null`, the slot is dropped.
   - `BROLL_VISION_CAP` (default 10) caps vision calls across the whole clip.
     Once exhausted, remaining anchors take Pexels top-1 unverified (matches
     legacy behavior); first unverified slot is logged.

If Claude returns zero raw picks, or `PEXELS_API_KEY` is missing, or all
queries miss, the skill emits `{"picks": []}` and exits 0.

## Status

Split-out from the legacy `broll` skill per May26-spec §2. Pair with
`broll-composite` to render. The legacy `broll` skill remains in place as a
non-split fallback.
