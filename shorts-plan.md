# Shorts Pipeline — Plan

Parallel to `youtube/livestream-edit-plan.md`. Same input, different
output product. This is a living design doc — update it as research
closes open questions.

## Product

From one long gameplay VOD, automatically produce N vertical 9:16
shorts (30-60s each), each with gameplay reframed, facecam visible,
and burned subtitles. Ready to upload to TikTok / YouTube Shorts /
Reels.

## Phases

### Phase 1 — Research (report only, no code)

Questions to answer before writing a pipeline:

1. **Reframing:** Of the viable approaches (static center-crop,
   saliency-guided pan, YOLO/subject-tracked crop, SAM2 mask-driven
   crop), which can we run locally on this Mac in under real-time?
   What's the quality ceiling on a known-good 30s test clip for each?
2. **Facecam localization:** Can we reliably detect the facecam overlay
   region in a single-mux stream? (MediaPipe face box + stability over
   time is probably sufficient.) If the facecam moves across sessions,
   how often does it actually move?
3. **Subtitle styling:** ffmpeg `subtitles=` with `force_style`, or a
   karaoke-style per-word renderer (aeneas / whisperX word alignment
   + per-word SRT → burn)? Word-level is the modern TikTok look; start
   with line-level and upgrade if needed.
4. **Selection contract:** Can Warren's `edit-instructions.json` drive
   shorts directly, or do shorts need a different `standalone_score`
   weighting (e.g., "has a clean hook in first 3s" as a first-class
   signal)? Probably a new scorer on top of the same candidate list.
5. **Hook detection:** Can we cheaply detect "question → beat → answer"
   or "setup → reaction" shapes in the transcript? Rule-based first
   (look for `"wait", "oh", "no way", "let's go"` near z-score peaks),
   LLM later if rules underperform.
6. **Loudness + platform specs:** What target LUFS, peak, bitrate, and
   codec settings do the three platforms actually require / reward?

Deliverable: `sota-shorts.md` (peer of eddy's `sota-research.md`) with
a verdict + specific techniques to adopt.

### Phase 2 — MVP

End-to-end, ugly but working. One layout, deterministic pipeline.

**Input:** `source/stream.mp4` (symlink to the youtube rig source),
optionally `input/edit-instructions.json` (reuse Warren's).

**Output:** `output/shorts/short-{01..N}.mp4`, `output/shorts.json`.

**Stages:**

1. Ingest — resolve source, load candidate moments (reuse Warren's list
   if present, else call a fallback picker — pysceneddetect + RMS
   gated by transcript keyword list).
2. Score-for-shorts — rerank with shorts-specific weights (standalone
   hook > total reaction intensity).
3. Trim — pick start/end so the clip is 30-60s and the first 2s are
   inside the payoff window, not the wind-up.
4. Transcribe the clip window (`mlx-whisper` on the 60s slice, not the
   whole stream — cheap).
5. Compose — hardcoded layout v0:
   - Vertical frame 1080×1920.
   - Facecam PiP: square crop of detected face region, 400×400, placed
     top-center.
   - Gameplay: center-crop of the remaining region to 1080× ~1400.
   - Subtitles burned, bottom-third, white + black outline, 72pt.
6. Encode — H.264 high, CRF 20, AAC 192k, -14 LUFS normalize.
7. Write `shorts.json` with per-short metadata.

**Acceptance:** the test stream produces ≥ 3 shorts that a human would
not immediately scroll past.

### Phase 3 — Iterate (only after MVP exists)

Candidates, prioritize by what's visibly broken on the MVP output:

- Saliency / tracked reframing for gameplay action
- Word-level karaoke subtitles
- Auto-generated hook overlays ("He had NO IDEA this was coming")
- LLM-picked titles and hashtags
- Multi-variant output (same moment, two different hooks) for A/B

## Local vs. cloud inference — decision rule

- **Local first:** any per-frame or per-second signal (saliency,
  face detect, scene detect, ASR, loudness).
- **Cloud (Haiku):** semantic ranking on transcript, hook generation,
  caption polish. These are LLM-native and low volume (dozens of calls
  per run, not thousands).
- **Cloud (Sonnet):** only when Haiku demonstrably underperforms on a
  concrete eval, and only for the step where it does.

If a local model needs to run thousands of times (e.g., reframe tracker
on every frame of 2 hours), and it's CPU-bound, either downscale before
running it or mint a helper polecat to parallelize. Don't block shorty's
main loop on a 40-minute model run.

## Open questions (file as beads when you pick them up)

- Where does the *next* source video come from? Is this a one-off test
  on the existing stream or an ongoing pipeline tied to a channel?
- Who is the target audience — the streamer themselves uploading, or a
  demo artifact for the user's portfolio?
- Any legal / rights constraints on the source stream? (probably not if
  it's user's own content, but document it.)
