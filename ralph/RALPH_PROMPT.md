# Shorts pipeline — implementation loop

## Goal

Build a working YouTube-URL → vertical-shorts pipeline as atomic Claude
Code skills under `.claude/skills/<name>/SKILL.md`, plus a top-level
entrypoint that chains them.

End state: I (or any user) can run the entrypoint with a YouTube URL and
get finished 9:16 1080×1920 MP4 shorts on disk under `./out/<source-id>/`,
with burned subtitles, loudnormed audio, and ffprobe-verified validity.

## Stack constraints (do NOT deviate)

- **Transcription:** whisper.cpp local. Binary + model paths come from `.env`
  (`WHISPER_CLI`, `WHISPER_MODEL`). Never hardcode.
- **Semantic decisions** (pick-segments, pick-speaker): call Claude through
  the host session or a `/crew` tmux member. **NO Anthropic API key, no SDK.**
- **All media ops:** ffmpeg / ffprobe.
- **Face detection:** MediaPipe (Python).
- **Ingest:** yt-dlp.
- **No monolith.** One atomic op per skill. Two operations means two skills.
- **JSON between skills.** Data passes as JSON files on disk under
  `./work/<source-id>/` (e.g. `ingest.json`, `transcript.json`, `faces.json`,
  `speaker.json`, `segments.json`). Skills read inputs and write outputs by
  path, never thread state in memory.

## What to build

Beads are filed. Run `bd ready` to find unblocked work and `bd show <id>`
for details. The set (ignore IDs that have changed):

- `shorts-x2w` yt-dlp ingest (URL → source.mp4 + ingest.json)
- `shorts-b47` transcribe (whisper.cpp → transcript.json)
- `shorts-a3d` detect-faces (MediaPipe → faces.json)
- `shorts-kw3` pick-speaker (Claude → speaker.json)
- `shorts-gvv` pick-segments (Claude → segments.json, N spans)
- `shorts-fiu` cut-clip (ffmpeg trim per span)
- `shorts-24x` reframe-vertical (ffmpeg crop path → 1080×1920)
- `shorts-th6` burn-subtitles (ASS + ffmpeg)
- `shorts-eea` loudnorm (ffmpeg two-pass)
- `shorts-yk1` qc-clip (ffprobe sanity)
- `shorts-wxo` save-local (`./out/<source-id>/clip-N.mp4`)
- `shorts-n19` entrypoint (chains all of the above; blocked until skills land)

Each skill's `.claude/skills/<name>/SKILL.md` already exists as a scaffold.
Fill in the contract (frontmatter: `name`, `description`, `allowed-tools`,
`user-invocable`) and the procedure. Implementation code goes alongside
the SKILL.md if it's a script (e.g. `transcribe.sh`, `detect_faces.py`).

## Order of attack

1. Foundations first: `ingest`, `transcribe`, `detect-faces`, `cut-clip` —
   none depend on each other. Test each on a short local video.
2. Claude-driven: `pick-speaker` and `pick-segments`. These call Claude;
   write their I/O contract in JSON so they can be re-run cheaply.
3. Per-span transforms: `reframe-vertical`, `burn-subtitles`, `loudnorm`,
   `qc-clip`, `save-local`. These can be developed in parallel.
4. Last: `shorts-n19` entrypoint. A shell script that walks the chain.

## Prove-it-works (project-specific evidence)

A skill is NOT done until you have a concrete artifact proving it ran:

- `transcribe`: produced `transcript.json` from a real audio file.
- `detect-faces`: produced `faces.json` with at least one detected box.
- `cut-clip`: produced an MP4 of the requested duration (verify with
  `ffprobe -show_entries format=duration`).
- `reframe-vertical`: produced an MP4 whose width=1080 and height=1920.
- `burn-subtitles`: produced an MP4 with visibly burned text (extract one
  frame with ffmpeg and confirm the text pixels are present).
- `loudnorm`: produced an MP4 whose integrated loudness is near -14 LUFS
  (verify with `ffmpeg -i ... -af loudnorm=print_format=json -f null -`).
- `qc-clip`: rejects an obviously broken clip (zero-byte or 0-duration).
- `save-local`: file exists at expected path.
- `entrypoint`: end-to-end run on a 2-3 minute test video produces ≥1
  finished clip under `./out/`.

Paste the ffprobe / ls / loudnorm-log output into the bead `--notes`
before closing it. "I wrote the script" is not done.

## Source video for live testing

Use a short, safe public test clip (e.g. Big Buck Bunny, or any
≤3-minute creative-commons video). Do NOT pull a long copyrighted stream
for development testing — keeps iteration fast and avoids storage bloat.

## When all beads close

Don't stop. Create new beads for hardening:
- E2E test on a 10-minute video, time each stage, log to `runs/`.
- Cache layer: skip ingest/transcribe/detect-faces if `work/<id>/` already
  has the artifact and source hash matches.
- README at repo root describing the pipeline and how to invoke.
- Per-skill README examples.

Memories (`bd memories`) hold the goal and constraints — re-read them at
the start of each pass.
