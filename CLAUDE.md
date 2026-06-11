# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project. It is the **single source of truth** for "the pipeline" — when the user says "run the pipeline", "rerun the pipeline", or "the pipeline", they mean exactly what is documented here.

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

## What This Project Is

A local-first YouTube-shorts factory. Feed it a long-form video (podcast, talk, vlog); it transcribes locally, has Claude pick the most clip-worthy story spans, edits each into a tight 9:16 short (filler cut, pace tightened, punch-in reframe, B-roll cutaways, karaoke captions, title card, branding, music), and saves finished `.mp4`s under `./output/<source-slug>/<title-slug>.mp4`. The channel brand is **@C0BALT_CUT** (see `brand/BRAND.md`).

## Architecture

Atomic Claude Code skills, one per video-editing operation. Each skill lives at `.claude/skills/<name>/SKILL.md` and is independently invocable. Skills chain into the full shorts pipeline but are NOT a monolithic codebase.

**Stack:** whisper.cpp (local transcription) + Claude (semantic decisions, via host session or `/crew` tmux members — no API key) + ffmpeg (all media ops) + MediaPipe/OpenCV (faces, saliency) + PIL (all text rendering — the local ffmpeg has NO libass/drawtext, so every text overlay is a transparent PNG composited by ffmpeg).

**No Anthropic API key.** Claude-driven skills (`segment-topics`, `pick-segments`, `verify-coherence`, `bookend-trim`, `trim-filler`, `verify-bookends`, `chunk-captions`, `broll-pick`, `generate-title`, `pick-mood`) run via `claude -p` or long-lived Claude tmux panes on the user's subscription. mcptube's own `discover` command needs an LLM API key and is therefore FORBIDDEN — use the mcptube-bundled `yt-dlp` ytsearch instead.

## Entrypoints

| Entrypoint | What it is | When to use |
|---|---|---|
| `start.sh` / `/start` | **Primary orchestrator.** Runs the pipeline across long-lived tmux panes (`shorts-<id>-analysis`, `-editor-NN`, `-captions-NN`, `-completion-NN`), parallelizing spans up to `SHORTS_MAX_PAR`. Resumable: each phase skips when its output artifacts exist. | Any "run the pipeline" request |
| `shorts.sh` | Legacy sequential fallback: same skill chain, single process, `claude -p` per step. | Debugging a single skill in isolation, or when tmux is unavailable |

```bash
bash start.sh <youtube-url>      # fresh run
bash start.sh <11-char-yt-id>    # bare ID
bash start.sh work/<source-id>   # reuse an already-ingested source
bash start.sh url1 url2 ...      # batch, sequential per video
bash shorts.sh <url> [n=5] [dmin=20] [dmax=60]
```

`start.sh` phases: **1** srcprep pane (ingest + transcribe) → **2** analysis pane (segment-topics → pick-segments → verify-coherence) → **3** per-span editor panes (bookend-trim → cut/assemble → trim-filler → cut-filler → tighten-pace → verify-bookends → fill-vertical) → **4** per-span captions panes (chunk-captions → broll-pick → broll-composite → burn-subtitles → generate-title → title-transition → source-credit → watermark → loudnorm) → **5** per-span completion panes (like-subscribe-overlay → pick-mood → bg-music → qc-clip → name-short → save-local) → broll-cleanup once at end. Resume markers: phase 2 skips on `clip_NN.vert.mp4` + `.path` sidecars; phase 3 on `clip_NN.leveled.mp4`; phase 4 on `clip_NN.done.completion`. Failures write `clip_NN.fail[.captions|.completion]` and downstream phases skip that span.

## The Pipeline (canonical — every skill below MUST run on a full pipeline invocation)

```
source video
  ├─ ingest           (yt-dlp → work/<id>/source.mp4 + ingest.json)
  ├─ transcribe       (whisper.cpp local → transcript.json, word-level timestamps)
  ├─ segment-topics   (Claude → topics.json)
  ├─ pick-segments    (Claude over transcript + RMS + topics → segments.raw.json, N spans; each span carries `cuts`: 1-3 within-topic source ranges assembled into one story)
  ├─ verify-coherence (tighten incoherent spans to the dominant topic → segments.coherent.json; multi-cut spans pass through untouched)
  ├─ bookend-trim     (Claude snaps each span's [t0,t1] to sentence boundaries → segments.json; for multi-cut, snaps the first cut's start + last cut's end)
  └─ per span:
       cut-clip (assemble: when `cuts` has >1 range, cut each precisely + concat into one clip; assemble.py builds the joined clip-local transcript)
        → rebase (single-cut spans only; rebase.py — multi-cut uses assemble.py)
        → trim-filler + cut-filler     (Claude marks filler / trail-offs / digressive asides → keeps.json; cut-filler applies it)
        → tighten-pace                 (collapse remaining inter-word silences >0.18s; re-times the transcript)
        → verify-bookends              (Claude VISION gate on first/last 1.5s: keep / inward-trim / drop; inward-only, never extends)
        → fill-vertical                (1080x1920 punch-in crop, fills the frame — NO blur bars, NO letterbox; biases to the dominant speaker across shots, frames non-speaker reaction shots looser so it never hero-frames a listener)
        → chunk-captions               (Claude groups transcript → chunks.json; runs AHEAD of b-roll so cutaway windows snap to chunk boundaries)
        → broll-pick                   (Claude contextual/scene anchors → mcptube/yt-dlp cutaways → broll_plan.json; vision verify judges tonal fit + rejects literal-but-wrong; per-clip slot names, dense ~6-10 windows, BROLL_VISION_CAP default 16)
        → broll-composite              (full-frame hard-cut cutaways onto the vertical clip, saliency-cropped not center; podcast audio continuous)
        → burn-subtitles               (chunk-karaoke PNG overlay, RMS-aligned, burned ON TOP of the b-roll)
        → generate-title + title-transition (Claude title ≤7 words ALL-CAPS → silent animated intro card, pop-in + flash + shake)
        → source-credit                (persistent "Original video: <title>" credit, TOP chyron y≈4%)
        → watermark                    (persistent @C0BALT_CUT mark, bottom-anchored y≈97.5% — opposite the credit)
        → loudnorm                     (two-pass to -14 LUFS / -1.5 dBTP)
        → like-subscribe-overlay       (animated CTA in the last ~4s + bell SFX)
        → pick-mood + bg-music         (Claude picks ./songs/<mood>/ from clip transcript; bed at ~-18dB, last 5 picks blacklisted via ./songs/.recent)
        → qc-clip                      (ffprobe gate: duration 15-90s, size >100KB)
        → name-short + save-local      (title → kebab-case filename → ./output/<source-slug>/<title-slug>.mp4)
  └─ broll-cleanup     (ONCE at end of run: evict only this run's mcptube b-roll ingests + local broll/* cache; broll_plan.json persists)
```

**Hard rules for any "rerun the pipeline" / full-pipeline request:**
- Use `fill-vertical` for the 9:16 reframe — punch-in crop that FILLS the frame (face ~45% height, lip-activity speaker pick, saliency crop for no-face shots). NEVER letterbox, NO blur bars. Both `fit-vertical` and `reframe-vertical` are retired/deleted (they linger only in the gitignored stale `.agents/` copy — never resurrect them). It clusters faces across shots to find the dominant speaker, biases the per-shot pick toward whoever is actually talking, and frames a non-speaking reaction/listener shot LOOSER so the short never dwells hero-framed on the wrong person.
- pick-segments builds each short from `cuts` — 1-3 NON-contiguous source ranges within ONE topic, assembled into one story (skip the sag, keep hook→payoff). The `cut-clip` step cuts each range precisely and concats; `assemble.py` joins the clip-local transcript so all downstream skills stay synced. A single-cut short is `cuts:[[t0,t1]]` and takes the plain `rebase.py` path. Multi-cut spans bypass verify-coherence tightening (already tightened by construction).
- `verify-bookends` runs AFTER `tighten-pace` and BEFORE `fill-vertical`. It is INWARD-ONLY (bookend-trim already had its outward chance) and may drop a span only on cleanliness failures requiring >2s of trim — never on hook weakness alone. Disable with `VERIFY_BOOKENDS=0`.
- `chunk-captions` runs BEFORE `broll-pick` (b-roll windows snap to whole caption-chunk boundaries — no mid-word cuts).
- `broll-composite` runs AFTER `broll-pick` and BEFORE `burn-subtitles` — captions must burn OVER the cutaways, never under them.
- B-roll cutaways are full-frame hard cuts (entire 1080×1920 replaced, scale-cover + SALIENCY crop toward the action — not blind center — no bars, no crossfade/zoom). Podcast audio is continuous (stream-copied); b-roll audio is always dropped. Bottom-bar/letterbox b-roll = regression.
- `broll-pick` anchors are CONTEXTUAL/scene-level, not literal keyword objects — footage must match the story's tone (a tense "red dot" beat wants a sniper/laser sight, NOT a cat laser toy). Vision verify is given the spoken context and rejects literal-but-wrong matches. Aim dense (~6-10 windows where a sensible visual exists). B-roll files are namespaced per clip (`<clip>_broll_NN.<ext>`) in the shared `broll/` dir — NEVER reuse bare `broll_NN.mp4` slot names across spans (cross-span contamination bug).
- `broll-pick` discovery uses the mcptube-bundled `yt-dlp` ytsearch, NOT `mcptube discover` (the latter needs an LLM API key the stack forbids). Vision verify via `claude -p`; total vision calls bounded by `BROLL_VISION_CAP` (default 16). Each window gets at most 2 query attempts (original + one literal↔metaphorical rewrite).
- `broll-cleanup` runs exactly ONCE at end of run, evicting only `video_id`s in each `broll_plan.json`'s `ingested_video_ids` — never the podcast source. It must never modify or delete `broll_plan.json`.
- `title-transition` is mandatory and runs AFTER `burn-subtitles`, BEFORE `source-credit`. The title text comes from `generate-title`.
- `bookend-trim` runs AFTER `verify-coherence` and BEFORE `cut-clip`. It snaps each span's `[t0, t1]` to a clean sentence boundary so shorts don't end mid-sentence (whisper output has punctuation stripped, so Claude infers boundaries — heuristics on `.!?` won't work).
- `like-subscribe-overlay` runs AFTER `loudnorm` and BEFORE `bg-music`. It overlays an animated CTA on the last ~4s of the clip.
- `source-credit` runs AFTER `title-transition` and BEFORE `watermark`. It bakes a persistent "Original video: <title>" credit as a TOP chyron (banner top at y≈4% of frame height), clear of the lower-third captions and the centered title card. Title is read from `work/<id>/ingest.json`.
- `watermark` runs AFTER `source-credit` and BEFORE `loudnorm`. It bakes the persistent `@C0BALT_CUT` channel mark bottom-center (bottom-anchored at y≈97.5%) — the vertical opposite of the credit. Brand colors from `brand/BRAND.md`: Platinum `#E8ECF1` type with the slashed-zero in Sapphire Glow `#2E6BFF`. The CTA overlay composites on top of it in the last ~4s, which is intended.
- The caption/accent blue everywhere (burn-subtitles active word, title-transition accent word, source-credit label, watermark zero, CTA accent) is Sapphire Glow `#2E6BFF` from `brand/BRAND.md` — matched to the channel pfp/banner gem. Electric cyan `#00E5FF` is retired; reintroducing it is a regression. All overlay text is Impact (`/System/Library/Fonts/Supplemental/Impact.ttf`) with a thick black stroke.
- Final shorts are named from the title: `name-short` slugs `generate-title`'s output into `<kebab-title>.mp4`, and `save-local` puts it in `output/<source-title-slug>/`. Generic `short_NN.mp4` names in output/ = the orchestrator forgot to pass the name through.
- If `start.sh`/`shorts.sh` does not invoke every skill above in the listed order, the entrypoint is wrong — fix the entrypoint, do not silently skip skills.
- Verify after a run: every saved `output/<source-slug>/*.mp4` must be 1080x1920 (full-bleed punch-in, NO blur bars), have a title card on the first ~2.5s, AND have a CTA card on the last ~4s. If any is missing, the pipeline regressed.
- `sfx-beats` (riser/hit/stinger at tension peaks) exists but is NOT in the canonical chain — only run it when explicitly asked.

## work/<id>/ Artifact Map

Every source gets `work/<sha1(url)[:10]>/`. Source-level files:

| File | Written by | Contents |
|---|---|---|
| `source.mp4`, `ingest.json` | ingest | video + `{id, url, title, duration, fps, width, height, path}` |
| `transcript.json` | transcribe | `{source, language, words:[{t0,t1,w}], segments:[{t0,t1,text}]}` |
| `topics.json` | segment-topics | `{topics:[{t0,t1,title,summary}]}` |
| `segments.raw.json` | pick-segments | `{shorts:[{t0,t1,cuts,topic,rationale,title_suggestion,hook_score,structure_score,overall_score}]}` |
| `segments.coherent.json` | verify-coherence | same + `coherence_verdict`/`coherence_note` |
| `segments.json` | bookend-trim | final spans + `bookend_note` |
| `broll/` | broll-pick | downloaded cutaways `<clip>_broll_NN.<ext>` (evicted by broll-cleanup) |
| `_pane/` | pane.sh | per-step `in.txt`/`out.txt`/`out.done` for tmux Claude dispatch |

Per-span files chain as `clip_NN.<stage>`: `.mp4` (cut) → `.transcript.json` (rebased) → `.keeps.json` + `.trim.mp4` + `.trim.transcript.json` (filler cut) → `.tight.mp4` + `.tight.transcript.json` (pace) → `.verify.json` (bookends verdict) → `.vert.mp4` (9:16) → `.chunks.json` → `.broll_plan.json` + `.brolled.mp4` → `.sub.mp4` (captions) → `.title.txt` + `.titled.mp4` → `.credited.mp4` → `.marked.mp4` → `.leveled.mp4` (loudnorm) → `.ctaed.mp4` → `.mood.txt` + `.final.mp4` (music). Multi-cut spans also leave `clip_NN.cut_JJ.mp4` pieces + `clip_NN.cuts.txt` concat list.

**Sidecars:** `.*meta` files (`.tfmeta`, `.tpmeta`, `.ttmeta`, `.vbmeta`, `.scmeta`, `.lsmeta`, `.bgmeta`, `.pickmeta`, `.compmeta`) are mtime+param cache signatures — every skill is idempotent and skips when output is newer than inputs and the signature matches. `.path` files (`vert.path`, `ctx.path`, `leveled.path`) hand artifact locations between start.sh phases. `clip_NN.fail*` / `clip_NN.done.completion` are phase failure/resume markers.

## Claude Dispatch (pane.sh)

`_lib/pane.sh` provides `run_claude_step <step> <prompt> <reply>`: with no `SHORTS_PANE` it runs `claude -p --output-format text`; with `SHORTS_PANE=<tmux-session>` + `SHORTS_PANE_MODE=chat` (what start.sh uses) it messages a long-lived interactive Claude pane, which writes `out.txt` + touches `out.done`, polled every `PANE_TICK` (6s) up to `PANE_TIMEOUT` (1800s). Claude-driven skills all follow the same shape: `build_prompt.py` → `run_claude_step` → `parse_reply.py` (with a deterministic fallback if the reply doesn't parse).

## Environment

`.env` holds source-of-truth paths (never hardcode): `WHISPER_BIN`, `WHISPER_MODEL`, `OUTPUT_DIR`. Runtime knobs: `SHORTS_N` / `SHORTS_DMIN` / `SHORTS_DMAX` (span count + duration bounds), `SHORTS_MAX_PAR` (parallel spans, default 1), `SHORTS_ENCODER` (`videotoolbox`|`x264`) via `_lib/encode.sh`, `BROLL_VISION_CAP` (default 16), `BROLL_PICK=0` / `VERIFY_BOOKENDS=0` (disable those gates), `MCPTUBE_URL` (default `http://127.0.0.1:9093/mcp`), `PANE_TICK` / `PANE_TIMEOUT`.

## File Tree (jump here instead of running find/ls)

```
shorts/
├── CLAUDE.md                  # this file — canonical pipeline definition
├── README.md                  # human-facing overview
├── AGENTS.md                  # STALE (pre-pivot "Codex" era) — do not trust; this file wins
├── SPEC.md                    # quality-pass redesign spec (coherence/titles/chunked captions)
├── SPEC-broll.md              # B-roll suite spec (broll-pick/composite/cleanup)
├── SPEC-fill-vertical.md      # punch-in 9:16 reframe spec (replaced fit-vertical)
├── SPEC-pick-segments.md      # engagement-scoring prompt spec
├── May26-spec.md              # /start tmux orchestration spec
├── start.sh                   # PRIMARY entrypoint — 4-phase tmux pane orchestrator, resumable
├── shorts.sh                  # legacy sequential entrypoint (same chain, no panes)
├── assemble.py                # multi-cut: joins per-cut transcripts into one clip-local transcript
├── rebase.py                  # single-cut: rebases full transcript to clip-local [t0,t1] window
├── ralph.sh                   # autonomous /crew loop runner (re-dispatches ralph/RALPH_PROMPT.md)
├── ralph/RALPH_PROMPT.md      # standing prompt for the ralph loop
├── brand/BRAND.md             # @C0BALT_CUT identity: Cobalt #0047AB, Sapphire Glow #2E6BFF, Carbon Black #101418, Platinum #E8ECF1
├── .env                       # WHISPER_BIN, WHISPER_MODEL, OUTPUT_DIR (gitignored)
├── songs/<Mood>/*.mp3         # bg-music library (Calm, Energetic, Funny, Story, ... 13 mood folders)
├── songs/.recent              # last-5 track blacklist (bg-music)
├── samples/title-sfx/         # title-card SFX reference samples
├── reference_shorts/          # target-look frame grabs used by the SPECs
├── work/<id>/                 # per-source working dirs (see Artifact Map above)
├── output/<source-slug>/      # finished shorts, <title-slug>.mp4
├── .agents/                   # STALE gitignored copy of old skills (has retired fit-vertical/reframe-vertical) — never edit
└── .claude/
    ├── commands/start.md      # /start command definition
    ├── crew/ralph/            # ralph crew-member identity (CLAUDE.md, BIO.md, state-*.json)
    └── skills/
        ├── _lib/pane.sh       # run_claude_step: claude -p vs tmux-pane dispatch + polling
        ├── _lib/encode.sh     # vt_args/vt_threads: VideoToolbox vs libx264 encoder args
        │   # — selection phase —
        ├── ingest/            # ingest.sh: yt-dlp → source.mp4 + ingest.json
        ├── transcribe/        # transcribe.sh: whisper.cpp → word-level transcript.json
        ├── segment-topics/    # segment-topics.sh + build_prompt/parse_reply.py: Claude topic chapters
        ├── pick-segments/     # pick-segments.sh + rms.py + build_prompt/parse_reply.py: Claude span picks w/ cuts + hook scores
        ├── verify-coherence/  # verify-coherence.sh: Claude keep/tighten gate per span
        ├── bookend-trim/      # bookend-trim.sh + trim.py: Claude sentence-boundary snap (±6s)
        │   # — per-span edit phase —
        ├── cut-clip/          # cut-clip.sh: ffmpeg [t0,t1] trim (stream-copy or reencode)
        ├── trim-filler/       # trim-filler.sh: Claude marks filler → keeps.json + trimmed transcript
        ├── cut-filler/        # cut-filler.sh: ffmpeg select/aselect applies keeps.json
        ├── tighten-pace/      # tighten-pace.sh + plan.py: collapse gaps >0.18s → 0.08s (0.15s after sentences)
        ├── verify-bookends/   # verify-bookends.sh: Claude VISION gate on head/tail 1.5s (keep/trim/drop, inward-only)
        ├── fill-vertical/     # fill-vertical.sh + fill_vertical.py + models/face_landmarker.task: punch-in 9:16 (MediaPipe faces, lip-activity speaker pick, OpenCV saliency fallback)
        │   # — captions & b-roll phase —
        ├── chunk-captions/    # chunk-captions.sh: Claude groups words into 3-6-word caption chunks
        ├── broll-pick/        # broll-pick.sh + pick_anchors/parse_anchors/verify_prompt/parse_verify/emit_plan.py: anchors → yt-dlp ytsearch → mcptube frames → Claude vision verify → broll_plan.json
        ├── broll-composite/   # broll-composite.sh + build_filter.py: full-frame hard-cut overlays, saliency crop
        ├── broll-cleanup/     # broll-cleanup.sh: end-of-run mcptube + broll/ cache eviction
        ├── burn-subtitles/    # burn-subtitles.sh + burn_subtitles.py: PIL PNG karaoke (Impact, Sapphire active word, RMS-aligned)
        │   # — finishing phase —
        ├── generate-title/    # generate-title.sh: Claude ≤7-word ALL-CAPS third-person title
        ├── title-transition/  # title-transition.sh + render_title.py: pop-in title card + flash + shake (2.5s)
        ├── source-credit/     # source-credit.sh + render_credit.py: top chyron "Original video: <title>" (y≈4%)
        ├── watermark/         # watermark.sh + render_watermark.py: @C0BALT_CUT bottom mark (y≈97.5%)
        ├── loudnorm/          # loudnorm.sh: two-pass ffmpeg loudnorm to -14 LUFS / -1.5 dBTP
        ├── like-subscribe-overlay/  # like-subscribe-overlay.sh + cta.html + build-cta.sh: alpha ProRes CTA banner (last ~4s) + bell SFX
        ├── pick-mood/         # pick-mood.sh: Claude picks songs/<mood>/ from clip transcript
        ├── bg-music/          # bg-music.sh: looped bed, vol 0.17 (~-18dB), .recent blacklist
        ├── sfx-beats/         # sfx-beats.sh + plan_sfx/make_sfx.py: riser/hit/stinger (NOT canonical — on request only)
        ├── qc-clip/           # qc-clip.sh: ffprobe duration/size gate
        ├── name-short/        # name-short.sh: title → kebab-case .mp4 filename (pure string op)
        └── save-local/        # save-local.sh: copy into output/<subdir>/<name>
```

## Conventions

- **One skill per atomic op.** Never bundle two operations into one skill. Tempting helpers (e.g. "transcribe + burn-subtitles") belong as separate skills that share I/O contracts.
- **JSON between skills.** Inter-skill data passes as JSON files on disk (transcript.json, topics.json, segments.json, etc.). Reading and writing is cheaper than threading state, and any skill can be re-run independently.
- **Every skill is idempotent.** mtime + `.*meta` signature checks mean re-running a skill with unchanged inputs is a no-op — safe to re-invoke any stage.
- **Source-of-truth paths in `.env`.** Binary paths (whisper-cli, model file) live in `.env`; never hardcode.
- **No CLAUDE.md per skill.** A single SKILL.md with frontmatter is the contract.
- **Claude-skill shape.** `build_prompt.py` → `run_claude_step` (pane.sh) → `parse_reply.py` with a deterministic fallback. Batch all spans into ONE Claude call where possible.

## Pre-pivot archive

`pipeline_v2.py` and the old whisperX/mlx_whisper pipeline are on the `archive/pre-pivot` branch. Salvageable snippets (ASS templating, loudnorm two-pass commands, crop-path smoothing) are noted in individual SKILL.md files. The gitignored `.agents/` dir and `AGENTS.md` are stale pre-pivot copies — ignore both; this file wins on any conflict.
