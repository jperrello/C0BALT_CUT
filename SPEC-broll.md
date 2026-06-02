# B-roll (mcptube) — Spec

> Cold-start handoff contract. A fresh agent with zero conversation context should be able to rebuild `broll-pick`, `broll-composite`, and `broll-cleanup` from this file alone. Supersedes the git-deleted Pexels-based versions (commits `d581824` added, `8939ec2` removed).

## Reference images
- **Target:** [`reference_shorts/sprite.png`](reference_shorts/sprite.png) — concrete nouns get full-bleed cutaways, interleaved beat-by-beat with the speaker (hippo appears underwater → in grass → running, intercut with the talking head across one topic).
- **Current (broken):** [`reference_shorts/sprite1.png`](reference_shorts/sprite1.png) — zero B-roll; "scaffolding," "Olympics," "Olympic shoes," "big sets" all go unillustrated.

## Working definition
Re-introduce B-roll cutaways into the canonical shorts pipeline. Three skills: `broll-pick` (Claude-driven sourcing via **mcptube**, replacing the retired Pexels path), `broll-composite` (pure-ffmpeg full-frame cut), and `broll-cleanup` (deferred cache eviction). During a B-roll window the **picture is fully replaced** by the cutaway; the podcast audio and burned karaoke captions continue on top. It is *not* a bottom-bar letterbox, *not* a change to Claude's anchor-word picking model, *not* Pexels in any form, *not* a new compositing engine.

## Who uses it and how
- `shorts.sh` / `start.sh` invoke the skills per span, in the per-clip chain (placement below).
- **Editors** read `broll_plan.json` to know, per cutaway, what it illustrates, where it sits in the short (`[t0,t1]`), and its source (video id/title/url + source timestamp) — this metadata is durable even after mcptube + local cache are evicted.

## Pipeline placement
Per-span chain becomes:
```
… → tighten-pace → fill-vertical (or fit-vertical until that ships)
   → chunk-captions            # transcript→chunks.json (pure transcript op)
   → broll-pick                # reads chunks.json + transcript + ingest.json → broll_plan.json
   → broll-composite           # full-frame cuts onto the vertical clip
   → burn-subtitles            # captions burn ON TOP of the brolled video
   → generate-title → title-transition → source-credit → loudnorm
   → like-subscribe-overlay → pick-mood → bg-music → qc-clip → save-local
… (end of whole run) → broll-cleanup
```
`chunk-captions` moves to *before* `broll-pick` (it only needs the transcript) so windows can snap to chunk boundaries. `broll-composite` runs *before* `burn-subtitles` so captions render over the cutaways.

## Core features

**broll-pick** (Claude + mcptube CLI; no API key):
- **Selective anchors.** Claude reads the clip transcript + `ingest.json` and picks only the **3–5 strongest visualizable nouns/topics** per clip (not every noun). Carries forward the old NOUN/VERB/EMOTION/PIVOT anchor model.
- **Interleaved, Claude-sized windows.** One topic spawns **multiple short cutaway windows** intercut with the speaker (back-and-forth, like the hippo sequence). Claude sets each window's length from speech rhythm, then it **snaps to whole `chunk-captions` boundaries** so no cut lands mid-word. Distinct windows on one topic prefer *different* footage (underwater / grass / running).
- **Sourcing per window:** `mcptube discover "<query>"` → ingest top candidate(s) with `mcptube add` → sample frames via `mcptube frame` across each candidate → show Claude (`claude -p`) the frame grid → Claude picks the best on-subject segment or rejects (`none`). On `none`, rewrite the query once (literal↔metaphorical / abstract↔embodied) and retry; second miss **drops the window** (no fallback footage — Pexels is gone).
- **Download:** once a segment `[s0,s1]` is chosen, `yt-dlp --download-sections "*s0-s1"` fetches **only that segment** into `work/<id>/broll/broll_NN.mp4` (lean cache). `[guess: segment download over whole-video to bound cache size; yt-dlp is in the mcptube venv]`
- **Vision cap** (`BROLL_VISION_CAP`, default 10) bounds Claude vision calls across the whole clip; once exhausted, remaining anchors are dropped (selective mode → no unverified footage).
- **Records** every ingested mcptube `video_id` for cleanup, and emits `broll_plan.json`.

**broll-composite** (pure ffmpeg):
- **Full-frame hard cut.** During each `[t0,t1]`, replace the entire 1080×1920 frame with the cutaway; instant cut in and out (no crossfade, no zoom). Video re-encoded only over the cutaway windows; **podcast audio stream-copied** for the whole clip (B-roll's own audio dropped).
- **Full-bleed fit, no bars.** Scale-to-cover the 16:9 source to 1080×1920 and crop to the salient action — same no-letterbox philosophy as [`SPEC-fill-vertical.md`](SPEC-fill-vertical.md). `[guess: center-cover crop; upgrade to saliency crop if fill-vertical exposes a reusable helper]`
- Zero picks (or all `clip_path`s missing) → copy-passthrough, exit 0.

**broll-cleanup** (deferred):
- Runs **once at end of the whole pipeline run**. For **only the B-roll source videos this run ingested** (tracked via the recorded `video_id`s — never the podcast source or unrelated library videos): `mcptube remove <id>` **and** delete the local `work/<id>/broll/*.mp4` cache.
- `broll_plan.json` is **not** touched — placement metadata persists for editors.

## broll_plan.json schema
```json
{
  "picks": [
    {"t0": 4.31, "t1": 6.02, "topic": "hippopotamus", "anchor_word": "hippopotamus",
     "query": "hippo swimming underwater", "clip_path": "/abs/work/<id>/broll/broll_03.mp4",
     "source": {"video_id": "abc123XYZ", "title": "...", "url": "https://youtu.be/abc123XYZ",
                "t0_src": 12.4, "t1_src": 14.1},
     "verified": true}
  ],
  "ingested_video_ids": ["abc123XYZ", "def456..."],
  "vision_calls_used": 4,
  "vision_cap": 10,
  "chunks_mtime": 1746000000.0
}
```

## Rules and edge cases
- **No anchors / all queries miss / discover empty** → `{"picks": [], "ingested_video_ids": []}`, exit 0; composite passes the clip through unchanged.
- **mcptube discover returns junk** → vision verify rejects → window dropped. The vision gate is the only quality guard.
- **Idempotency:** `broll-pick` caches on input+transcript+chunks mtimes (`<plan>.pickmeta`); `broll-composite` caches on input+plan mtimes (`<out>.compmeta`).
- **Window snapping:** a window covers ≥1 whole chunk; if a single chunk is too short, extend forward one chunk; if still degenerate, drop.
- **Audio:** never mix in B-roll audio; the podcast track is continuous.
- **CPU:** sample only K frames per candidate (≈3); reuse `_lib/encode.sh` thread caps (respects the `shorts-xv5` CPU-brick fix).

## Look and feel
Full-bleed 9:16 cutaways, hard cuts, interleaved beat-by-beat with the speaker on the strongest concrete nouns. Captions stay burned on top throughout. The "content" feel of `sprite.png`, never the bottom-bar webinar overlay of the old skill.

## Resolved decisions

### Density
Choice: Selective — 3–5 strong anchors per clip (old behavior).
Why: user picked it over matching the viral ref's ~40%-of-frames aggression; cheaper mcptube/yt-dlp churn and lower bad-match risk.

### Composite layout
Choice: Full-frame replacement, hard cut, full-bleed (no bars).
Why: user — "the b roll would be a cut … audio of the podcast and subtitles going, but the b roll is filled on the screen." Aligns with `SPEC-fill-vertical.md`'s never-letterbox rule. Retires the old bottom-bar (y=1332, 1080×520) layout.

### Interleave rhythm
Choice: Multiple short windows per topic, intercut with the speaker, distinct footage per window.
Why: user — "the clips will cut back and forth multiple times," confirmed by the hippo sequence in `sprite.png`.

### Window length
Choice: Claude picks per insert from speech rhythm, snapped to chunk boundaries.
Why: user chose "Claude picks per insert"; chunk-snap retained to prevent mid-word cuts.

### Sourcing + verify
Choice: mcptube `discover`→`add`→`frame`-sample → Claude vision verify (pick best / reject), query-rewrite once on miss.
Why: user picked "frame-sample + Claude vision verify"; robust for silent footage, reuses the old vision gate. Transcript-match rejected (whiffs on music-only stock footage).

### mcptube access
Choice: Skill calls the **mcptube CLI** (`discover/add/frame/remove`) and bundled `yt-dlp` directly from bash; Claude vision verify via `claude -p` with frame image paths.
Why: the CLI exposes every needed verb (verified via `mcptube --help` at `~/.local/pipx/venvs/mcptube/bin/mcptube`), so there's no MCP-in-subprocess problem; matches the "Claude via host/crew, no API key" stack rule.

### Cleanup scope + timing
Choice: End-of-run `broll-cleanup` evicts **both mcptube entry and local cache, but only for the B-roll source videos this run ingested**; `broll_plan.json` metadata persists.
Why: user — "Evict mcptube AND local cache … only the mcptube and local cache of the relevant video." The brolled mp4 is the deliverable; editors get placement metadata from the manifest.

## Technical constraints
- **Local, no API.** mcptube CLI at `~/.local/pipx/venvs/mcptube/bin/mcptube` (+ its bundled `yt-dlp`); ffmpeg for all media; `claude -p` (host session or `/crew`) for anchor pick + vision verify. Run Python with `python3`.
- **Three atomic skills** under `.claude/skills/{broll-pick,broll-composite,broll-cleanup}/`, each a `SKILL.md` + scripts; JSON (`broll_plan.json`) passes between them.
- **Wiring:** add all three to the canonical chain in `CLAUDE.md`'s pipeline block + hard rules, and to `shorts.sh` / `start.sh`. Move `chunk-captions` ahead of `broll-pick`.

## Out of scope
Changing the anchor-word picking logic; Pexels in any form; bottom-bar/letterbox B-roll; B-roll audio; crossfades/zoom transitions; continuous tracking pans; aggressive every-noun density; building `fill-vertical` (its own spec); editing the podcast source video.

## Decisions to double-check
1. **`fill-vertical` not built yet** — until it ships, `broll-composite` does its own center-cover crop. If `fill-vertical` lands a reusable saliency-crop helper, switch B-roll to it for consistent framing.
2. **YouTube footage licensing** — the viral ref uses arbitrary YouTube clips as B-roll. This spec follows that pattern; flagging in case sourcing should later be restricted to license-safe footage.
3. **mcptube `discover` latency/quota** — discover + add + frame-sample per anchor adds real wall-time and possible LLM-classify cost inside mcptube; eyeball on a real run and consider caching discover results per topic across clips of the same source.
