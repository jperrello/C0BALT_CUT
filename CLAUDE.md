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
  ├─ pick-segments    (Claude over transcript + RMS + topics → segments.raw.json, N spans; each span carries `cuts`: 1-3 within-topic source ranges assembled into one story)
  ├─ verify-coherence (tighten incoherent spans to the dominant topic; multi-cut spans pass through untouched)
  ├─ bookend-trim     (Claude snaps each span's [t0,t1] to sentence boundaries; for multi-cut, snaps the first cut's start + last cut's end)
  └─ per span:
       cut-clip (assemble: when `cuts` has >1 range, cut each precisely + concat into one clip; assemble.py builds the joined clip-local transcript)
        → rebase (single-cut spans only; multi-cut uses assemble.py)
        → trim-filler + cut-filler     (Claude cuts filler / trail-offs / digressive asides)
        → tighten-pace                 (collapse remaining inter-word silences >0.25s)
        → fill-vertical                (1080x1920 punch-in crop, fills the frame — NO blur bars, NO letterbox; biases to the dominant speaker across shots, frames non-speaker reaction shots looser so it never hero-frames a listener)
        → chunk-captions               (transcript → chunks.json; moved AHEAD of b-roll so cutaway windows snap to chunk boundaries)
        → broll-pick                   (Claude contextual/scene anchors → mcptube/yt-dlp cutaways → broll_plan.json; vision verify judges tonal fit + rejects literal-but-wrong; per-clip slot names, dense ~6-10 windows, BROLL_VISION_CAP default 16)
        → broll-composite              (full-frame hard-cut cutaways onto the vertical clip, saliency-cropped not center; podcast audio continuous)
        → burn-subtitles               (word-karaoke PNG overlay, burned ON TOP of the b-roll)
        → generate-title + title-transition (silent animated intro card)
        → source-credit                (persistent "Original video: <title>" credit, bottom third)
        → loudnorm                     (two-pass to -14 LUFS)
        → like-subscribe-overlay       (animated CTA in the last ~4s + bell SFX)
        → pick-mood + bg-music         (Claude picks ./songs/<mood>/ from clip transcript; bed at -18dB, last 5 picks blacklisted via ./songs/.recent)
        → qc-clip                      (ffprobe duration + size gate)
        → save-local                   (./output/<source>/short_NN.mp4)
  └─ broll-cleanup     (ONCE at end of run: evict only this run's mcptube b-roll ingests + local broll/*.mp4 cache; broll_plan.json persists)
```

**Hard rules for any "rerun the pipeline" / full-pipeline request:**
- Use `fill-vertical` for the 9:16 reframe — punch-in crop that FILLS the frame (face ~45% height, lip-activity speaker pick, saliency crop for no-face shots). NEVER letterbox, NO blur bars. Both `fit-vertical` and `reframe-vertical` are retired/deleted. It clusters faces across shots to find the dominant speaker, biases the per-shot pick toward whoever is actually talking, and frames a non-speaking reaction/listener shot LOOSER so the short never dwells hero-framed on the wrong person.
- pick-segments builds each short from `cuts` — 1-3 NON-contiguous source ranges within ONE topic, assembled into one story (skip the sag, keep hook→payoff). The `cut-clip` step cuts each range precisely and concats; `assemble.py` joins the clip-local transcript so all downstream skills stay synced. A single-cut short is `cuts:[[t0,t1]]` and takes the plain `rebase` path. Multi-cut spans bypass verify-coherence tightening (already tightened by construction).
- `chunk-captions` runs BEFORE `broll-pick` (b-roll windows snap to whole caption-chunk boundaries — no mid-word cuts).
- `broll-composite` runs AFTER `broll-pick` and BEFORE `burn-subtitles` — captions must burn OVER the cutaways, never under them.
- B-roll cutaways are full-frame hard cuts (entire 1080×1920 replaced, scale-cover + SALIENCY crop toward the action — not blind center — no bars, no crossfade/zoom). Podcast audio is continuous (stream-copied); b-roll audio is always dropped. Bottom-bar/letterbox b-roll = regression.
- `broll-pick` anchors are CONTEXTUAL/scene-level, not literal keyword objects — footage must match the story's tone (a tense "red dot" beat wants a sniper/laser sight, NOT a cat laser toy). Vision verify is given the spoken context and rejects literal-but-wrong matches. Aim dense (~6-10 windows where a sensible visual exists). B-roll files are namespaced per clip (`<clip>_broll_NN.<ext>`) in the shared `broll/` dir — NEVER reuse bare `broll_NN.mp4` slot names across spans (cross-span contamination bug).
- `broll-pick` discovery uses the mcptube-bundled `yt-dlp` ytsearch, NOT `mcptube discover` (the latter needs an LLM API key the stack forbids). Vision verify via `claude -p`; total vision calls bounded by `BROLL_VISION_CAP` (default 16).
- `broll-cleanup` runs exactly ONCE at end of run, evicting only `video_id`s in each `broll_plan.json`'s `ingested_video_ids` — never the podcast source. It must never modify or delete `broll_plan.json`.
- `title-transition` is mandatory and runs AFTER `burn-subtitles`, BEFORE `loudnorm`. The title text comes from `generate-title`.
- `bookend-trim` runs AFTER `verify-coherence` and BEFORE `cut-clip`. It snaps each span's `[t0, t1]` to a clean sentence boundary so shorts don't end mid-sentence.
- `like-subscribe-overlay` runs AFTER `loudnorm` and BEFORE `bg-music`. It overlays an animated CTA on the last ~4s of the clip.
- `source-credit` runs AFTER `title-transition` and BEFORE `loudnorm`. It bakes a persistent "Original video: <title>" credit in the bottom third (y≈70% of frame), positioned to not overlap the CTA banner (lower ~12%). Title is read from `work/<id>/ingest.json`.
- If `shorts.sh` does not invoke every skill above in the listed order, `shorts.sh` is wrong — fix the entrypoint, do not silently skip skills.
- Verify after a run: every saved `output/<source>/short_NN.mp4` must be 1080x1920 (full-bleed punch-in, NO blur bars), have a title card on the first ~2.5s, AND have a CTA card on the last ~4s. If any is missing, the pipeline regressed.

## Feedback loop (review.py)

Structured user feedback is how the pipeline improves between runs. NOT a skill; it is `review.py` at repo root.

1. **`python3 review.py`** serves a minimal form at `http://127.0.0.1:8765` (PORT env to change). The user pastes the path to a rendered short and scores stage-mapped sections (topic, hook, title, captions, broll, music, pacing, overall verdict), each keyed to the skills that own it, with a why line per score.
2. **Submit spawns an autonomous fixer.** The server appends the record to `feedback/history.jsonl`, writes a mission to `feedback/missions/<ts>.md`, and spawns a detached tmux session (`shorts-fix-<ts>`, crew-style: `claude --dangerously-skip-permissions --append-system-prompt-file <mission>` plus an unblocker watchdog for new-file Write prompts). The fixer has NO human in the loop: AskUserQuestion is prohibited, it never stops to clarify, it makes assumptions and records them in `feedback/missions/<ts>.report.md`.
3. **The fixer repairs the reviewed video in place.** Every section scored 4 or below gets fixed (only a 5 is left alone) by re-running the owning stages from the earliest change downstream. It renders to a temp file, QC-gates it, then replaces the original at the same path.
4. **The fixer patches the skills directly.** No taste/preference document exists; the skills ARE the memory. Every flagged failure becomes a concrete edit to the skill that caused it: prompt edits (bans, rules, reweighting) for prompt-driven stages, default-value changes for parameter-driven ones (captions, pacing, music level). Edits generalize the why text, never hardcode one video; when feedback contradicts an existing prompt rule, the user wins and the old rule is rewritten. Skill patches are committed and pushed citing the mission.

## Conventions

- **One skill per atomic op.** Never bundle two operations into one skill. Tempting helpers (e.g. "transcribe + burn-subtitles") belong as separate skills that share I/O contracts.
- **JSON between skills.** Inter-skill data passes as JSON files on disk (transcript.json, topics.json, segments.json, etc.). Reading and writing is cheaper than threading state, and any skill can be re-run independently.
- **Source-of-truth paths in `.env`.** Binary paths (whisper-cli, model file) live in `.env`; never hardcode.
- **No CLAUDE.md per skill.** A single SKILL.md with frontmatter is the contract.

## Pre-pivot archive

`pipeline_v2.py` and the old whisperX/mlx_whisper pipeline are on the `archive/pre-pivot` branch. Salvageable snippets (ASS templating, loudnorm two-pass commands, crop-path smoothing) are noted in individual SKILL.md files.
