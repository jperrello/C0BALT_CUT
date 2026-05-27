# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->


## Architecture

Atomic Claude Code skills, one per video-editing operation. Each skill lives at `.claude/skills/<name>/SKILL.md` and is independently invocable. Skills chain into the full shorts pipeline but are NOT a monolithic codebase.

**Stack:** whisper.cpp (local transcription) + Claude (semantic decisions, via host session or `/crew` tmux members — no API key) + ffmpeg (all media ops). Rails + Sidekiq is an optional wrapper, not required.

**No Anthropic API key.** Claude-driven skills (`pick-segments`, `segment-topics`, `verify-coherence`, `bookend-trim`, `trim-filler`, `chunk-captions`, `generate-title`, `pick-mood`) run inside the host Claude Code session or are dispatched to `/crew` members on tmux. All use the user's Claude subscription.

**Pipeline shape (canonical — every skill below MUST run on a full pipeline invocation):**
```
source video
  ├─ ingest           (yt-dlp → work/<id>/source.mp4 + ingest.json)
  ├─ transcribe       (whisper.cpp local → transcript.json)
  ├─ segment-topics   (Claude → topics.json)
  ├─ pick-segments    (Claude over transcript + RMS + topics → segments.raw.json, N spans)
  ├─ verify-coherence (tighten incoherent spans to the dominant topic)
  ├─ bookend-trim     (Claude snaps each span's [t0,t1] to sentence boundaries)
  └─ per span:
       cut-clip
        → rebase
        → trim-filler + cut-filler     (Claude cuts filler / trail-offs / digressive asides)
        → tighten-pace                 (collapse remaining inter-word silences >0.25s)
        → fit-vertical                 (1080x1920, blurred bars top/bottom — NO speaker-tracking crop)
        → chunk-captions + burn-subtitles (word-karaoke PNG overlay sequence)
        → generate-title + title-transition (silent animated intro card)
        → source-credit                (persistent "Original video: <title>" credit, bottom third)
        → loudnorm                     (two-pass to -14 LUFS)
        → like-subscribe-overlay       (animated CTA in the last ~4s + bell SFX)
        → pick-mood + bg-music         (Claude picks ./songs/<mood>/ from clip transcript; bed at -18dB, last 5 picks blacklisted via ./songs/.recent)
        → qc-clip                      (ffprobe duration + size gate)
        → save-local                   (./output/<source>/short_NN.mp4)
```

**Hard rules for any "rerun the pipeline" / full-pipeline request:**
- Use `fit-vertical`, NOT `reframe-vertical`. The speaker-tracking crop is currently disabled in the canonical chain; the blurred-bars 9:16 reframe is the source of truth.
- `title-transition` is mandatory and runs AFTER `burn-subtitles`, BEFORE `loudnorm`. The title text comes from `generate-title`.
- `bookend-trim` runs AFTER `verify-coherence` and BEFORE `cut-clip`. It snaps each span's `[t0, t1]` to a clean sentence boundary so shorts don't end mid-sentence.
- `like-subscribe-overlay` runs AFTER `loudnorm` and BEFORE `bg-music`. It overlays an animated CTA on the last ~4s of the clip.
- `source-credit` runs AFTER `title-transition` and BEFORE `loudnorm`. It bakes a persistent "Original video: <title>" credit in the bottom third (y≈70% of frame), positioned to not overlap the CTA banner (lower ~12%). Title is read from `work/<id>/ingest.json`.
- If `shorts.sh` does not invoke every skill above in the listed order, `shorts.sh` is wrong — fix the entrypoint, do not silently skip skills.
- Verify after a run: every saved `output/<source>/short_NN.mp4` must be 1080x1920, have a title card on the first ~2.5s, AND have a CTA card on the last ~4s. If any is missing, the pipeline regressed.

## Conventions

- **One skill per atomic op.** Never bundle two operations into one skill. Tempting helpers (e.g. "transcribe + burn-subtitles") belong as separate skills that share I/O contracts.
- **JSON between skills.** Inter-skill data passes as JSON files on disk (transcript.json, topics.json, segments.json, etc.). Reading and writing is cheaper than threading state, and any skill can be re-run independently.
- **Source-of-truth paths in `.env`.** Binary paths (whisper-cli, model file) live in `.env`; never hardcode.
- **No CLAUDE.md per skill.** A single SKILL.md with frontmatter is the contract.

## Pre-pivot archive

`pipeline_v2.py` and the old whisperX/mlx_whisper pipeline are on the `archive/pre-pivot` branch. Salvageable snippets (ASS templating, loudnorm two-pass commands, crop-path smoothing) are noted in individual SKILL.md files.
