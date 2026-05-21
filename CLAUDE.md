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

**Stack:** whisper.cpp (local transcription) + Claude (semantic decisions, via host session or `/crew` tmux members — no API key) + ffmpeg (all media ops) + MediaPipe (face boxes). Rails + Sidekiq is an optional wrapper, not required.

**No Anthropic API key.** Claude-driven skills (`pick-segments`, `pick-speaker`) run inside the host Claude Code session or are dispatched to `/crew` members on tmux. Both use the user's Claude subscription.

**Pipeline shape:**
```
source video
  ├─ transcribe       (whisper.cpp local)
  ├─ detect-faces     (MediaPipe)
  ├─ pick-speaker     (Claude over face boxes + transcript)
  ├─ pick-segments    (Claude over transcript + RMS) → N spans
  └─ per span:
       cut-clip → reframe-vertical → burn-subtitles → loudnorm → qc-clip → save-local
```

## Conventions

- **One skill per atomic op.** Never bundle two operations into one skill. Tempting helpers (e.g. "transcribe + burn-subtitles") belong as separate skills that share I/O contracts.
- **JSON between skills.** Inter-skill data passes as JSON files on disk (transcript.json, faces.json, speaker.json). Reading and writing is cheaper than threading state, and any skill can be re-run independently.
- **Source-of-truth paths in `.env`.** Binary paths (whisper-cli, model file) live in `.env`; never hardcode.
- **No CLAUDE.md per skill.** A single SKILL.md with frontmatter is the contract.

## Pre-pivot archive

`pipeline_v2.py` and the old whisperX/mlx_whisper pipeline are on the `archive/pre-pivot` branch. Salvageable snippets (ASS templating, loudnorm two-pass commands, crop-path smoothing) are noted in individual SKILL.md files.
