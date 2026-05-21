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
| `transcribe` | Video → JSON transcript with word timestamps (whisper.cpp local) |
| `detect-faces` | Per-frame face boxes via MediaPipe |
| `pick-speaker` | Claude picks active speaker face per span using boxes + transcript |
| `reframe-vertical` | Apply speaker-tracked 9:16 crop path via ffmpeg |
| `pick-segments` | Claude ranks transcript spans (+ RMS energy) → N clip-worthy spans |
| `burn-subtitles` | Build ASS from word times, burn with ffmpeg |
| `loudnorm` | Two-pass ffmpeg loudnorm to broadcast levels |
| `cut-clip` | ffmpeg trim to span |
| `qc-clip` | ffprobe sanity (duration, size) |
| `save-local` | Drop renders into `./output/<source-name>/` |

## Setup

```bash
cp .env.example .env  # paths to whisper-cli + your local GGML model
brew install ffmpeg whisper-cpp
pip install mediapipe opencv-python numpy
```

## Status

Skills are scaffolded as stubs. Implementation tracked in `bd ready`.

## Pre-pivot archive

The previous Python pipeline (whisperX, mlx-whisper, ranker/grader/subtitler in `pipeline_v2.py`) is preserved on the `archive/pre-pivot` branch.
