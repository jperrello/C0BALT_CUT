# shorts

Modular shorts production. Every step of turning a long horizontal video into a vertical short is an atomic Claude Code skill — each callable on its own, chainable into a full pipeline.

## Stack

- **whisper.cpp** (local, Metal) — transcription with word timestamps, using a local GGML model
- **Claude** (via Claude Code session + optional `/crew` tmux members) — segment ranking, active-speaker picking, semantic judgment. No API key required.
- **ffmpeg** — all media operations (cut, crop, loudnorm, burn-in)
- **MediaPipe** — face detection (boxes only; Claude picks the active speaker)
- **Rails + Sidekiq** — optional thin wrapper for upload UI + job queue (not required to use the skills)

## Goal

Upload a horizontal video → identify the speaker → reframe to keep them in shot → burn subtitles → cut N shorts → drop them in `./output/<source-video-name>/` for easy browsing.

## Skills

Skills live in `.claude/skills/<name>/SKILL.md`. Invoke any one directly via Claude Code, or chain them.

| Skill | Purpose |
|---|---|
| `ingest` | YouTube URL → `work/<id>/source.mp4` + `ingest.json` (yt-dlp) |
| `transcribe` | Video → JSON transcript with word timestamps (whisper.cpp local) |
| `fit-vertical` | 9:16 reframe with blurred bars top/bottom (no speaker tracking) |
| `pick-segments` | Claude ranks transcript spans (+ RMS energy) → N clip-worthy spans |
| `burn-subtitles` | Word-timed subtitles burned in as a PNG overlay sequence |
| `loudnorm` | Two-pass ffmpeg loudnorm to broadcast levels |
| `cut-clip` | ffmpeg trim to span |
| `qc-clip` | ffprobe sanity (duration, size) |
| `save-local` | Drop renders into `./output/<source-name>/` |

## Setup

```bash
cp .env.example .env  # paths to whisper-cli + your local GGML model
brew install ffmpeg whisper-cpp yt-dlp
pip install mediapipe opencv-python numpy
```

## Run the whole pipeline

```bash
./shorts.sh <youtube-url> [n=5] [dmin=20] [dmax=60]
```

Drives the full chain — ingest → transcribe → segment-topics → pick-segments →
verify-coherence → bookend-trim → per span (cut → trim-filler → tighten-pace →
fit-vertical → subtitles → title → loudnorm → CTA → bg-music → qc →
save). Intermediate JSON/video lands in `work/<id>/`; finished shorts in
`./output/<source-name>/`. Per-clip transcript is sliced to clip-local time by
`rebase.py`. Re-runs are cheap — every skill caches on mtime.

## Status

All skills implemented; `./shorts.sh` drives them end to end.

## Pre-pivot archive

The previous Python pipeline (whisperX, mlx-whisper, ranker/grader/subtitler in `pipeline_v2.py`) is preserved on the `archive/pre-pivot` branch.
