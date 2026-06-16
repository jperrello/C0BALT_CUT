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

**No Anthropic API key.** Claude-driven skills (`segment-topics`, `pick-segments`, `verify-coherence`, `pick-title-styles`, `bookend-trim`, `trim-filler`, `verify-bookends`, `chunk-captions`, `broll-pick`, `sfx-beats` comedy mode, `generate-title`, `pick-mood`) run via `claude -p` or long-lived Claude tmux panes on the user's subscription. mcptube's own `discover` command needs an LLM API key and is therefore FORBIDDEN — use the mcptube-bundled `yt-dlp` ytsearch instead.

## Entrypoints

| Entrypoint | What it is | When to use |
|---|---|---|
| `start.sh` / `/start` | **Primary orchestrator.** Runs the pipeline across long-lived tmux panes (`shorts-<id>-srcprep`, `-analysis`, and `SHORTS_MAX_PAR` span lanes `-lane-NN`). Each lane owns ONE pooled Claude pane reused across spans/phases with `/clear` between dispatches, so claude processes stay O(max_par), not O(spans). Resumable: each phase skips when its output artifacts exist. | Any "run the pipeline" request |
| `shorts.sh` | Legacy sequential fallback: same skill chain, single process, `claude -p` per step. | Debugging a single skill in isolation, or when tmux is unavailable |

```bash
bash start.sh <youtube-url>      # fresh run
bash start.sh <11-char-yt-id>    # bare ID
bash start.sh work/<source-id>   # reuse an already-ingested source
bash start.sh url1 url2 ...      # batch, sequential per video
bash shorts.sh <url> [n=5] [dmin=20] [dmax=40]
bash .claude/skills/scout-sources/scout-sources.sh   # what to clip NEXT (ranked candidates)
```

`start.sh` phases: **1** srcprep pane (ingest + transcribe) + analysis pane (segment-topics → pick-segments → verify-coherence → pick-title-styles) → **per-span lanes**: `SHORTS_MAX_PAR` lane workers each pull the next unclaimed span (mkdir-locked counter) and chain its three phases end-to-end — **edit** (bookend-trim → cut/assemble → trim-filler → cut-filler → tighten-pace → verify-bookends → fill-vertical), **captions** (zoom-punch → chunk-captions → broll-pick → broll-composite → burn-subtitles → sfx-beats comedy → generate-title → title-transition → brand-overlays → loudnorm), **completion** (like-subscribe-overlay → pick-mood → bg-music → qc-clip → name-short → save-local) — so early spans land in `./output/` while later spans are still editing, and Claude-wait in one lane overlaps ffmpeg in another. broll-cleanup runs once at end. Resume markers: edit skips on `clip_NN.vert.mp4` + `.path` sidecars; captions on `clip_NN.leveled.mp4`; completion on `clip_NN.done.completion`. Failures write `clip_NN.fail[.captions|.completion]` and cancel the rest of that span only; every phase attempt deletes its own stale marker first, so retried spans un-skip themselves (shorts-8m6).

## The Pipeline (canonical — every skill below MUST run on a full pipeline invocation)

`scout-sources` is the optional step BEFORE the pipeline: deterministic source discovery (keyless yt-dlp outlier scoring — views/day velocity, views-per-sub ratio, comment engagement, replay-heatmap peakiness) ranking niche-search candidates into `work/_scout/candidates.json`. Feed the winner to `start.sh`. Not part of the per-video chain.

```
source video
  ├─ ingest           (yt-dlp → work/<id>/source.mp4 + ingest.json + heatmap.json [most-replayed graph + chapters; absent on low-view sources, backfilled on cache-hit])
  ├─ transcribe       (whisper.cpp local → transcript.json, word-level timestamps)
  ├─ segment-topics   (Claude → topics.json; on long sources [RLM_TOPICS=1, or auto when duration ≥ RLM_TOPICS_MIN_SEC=1500s] runs rlm-assisted: chunks the full-resolution transcript into ~RLM_TOPICS_CHUNK_SEC=600s windows, dispatches ONE rlm-subcall subagent per chunk, synthesizes topics.json + candidates.hint.json — preserves back-half detail the single-prompt compression loses; single-prompt path is the deterministic fallback)
  ├─ pick-segments    (Claude over transcript + RMS + topics + replay heatmap + candidates.hint.json [rlm discovery hint, when present] → segments.raw.json, N spans; each span carries `cuts`: 1-3 within-topic source ranges assembled into one story; spans over most-replayed peaks get a deterministic overall_score bonus + `replay_quotient` field. The dmin–dmax window is the SOURCE-SELECTION budget, NOT delivered runtime — pick generously; downstream trim/tighten shave ~20-30%)
  ├─ verify-coherence (tighten incoherent spans to the dominant topic → segments.coherent.json; multi-cut spans pass through untouched)
  ├─ pick-title-styles (Claude, ONE batched call → title_style per span: slam|typewriter|glitch|bounce|cinematic; fit wins, variety as tiebreak, ≤⌈N/2⌉ per style, soft bias against the .recent log; any failure → least-used round-robin, never fatal)
  ├─ bookend-trim     (Claude snaps each span's [t0,t1] to sentence boundaries → segments.json; for multi-cut, snaps the first cut's start + last cut's end)
  ├─ verify-completeness (Claude arc-completeness gate in SOURCE coords: reads each span's assembled arc + tail lookahead → complete|needs_more_tail|truncated; nudges t1 + last cut's end OUTWARD to the landing sentence within dmax when the payoff got cut off. Non-fatal, idempotent, VERIFY_COMPLETENESS=0 disables. In start.sh runs per-span in phase 2 right after bookend-trim; in shorts.sh runs once over all spans. The OUTWARD counterpart to verify-bookends)
  └─ per span:
       cut-clip (assemble: when `cuts` has >1 range, cut each precisely + concat into one clip; assemble.py builds the joined clip-local transcript)
        → rebase (single-cut spans only; rebase.py — multi-cut uses assemble.py)
        → trim-filler + cut-filler     (Claude marks filler / trail-offs / digressive asides → keeps.json; cut-filler applies it)
        → tighten-pace                 (collapse remaining inter-word silences >0.18s; re-times the transcript)
        → verify-bookends              (Claude VISION gate on first/last 1.5s: keep / inward-trim / drop; inward-only, never extends)
        → fill-vertical                (1080x1920 punch-in crop, fills the frame — NO blur bars, NO letterbox; biases to the dominant speaker across shots, frames non-speaker reaction shots looser so it never hero-frames a listener)
        → zoom-punch                   (deterministic ~10% punch-in pulses at RMS-peak words snapped to word starts, 1-4 per clip, clear of the title card and tail; ZOOM_PUNCH=0 skips)
        → chunk-captions               (Claude groups transcript → chunks.json; runs AHEAD of b-roll so cutaway windows snap to chunk boundaries)
        → broll-pick                   (Claude contextual/scene anchors → mcptube/yt-dlp cutaways → broll_plan.json; vision verify judges tonal fit + rejects literal-but-wrong; per-clip slot names, dense ~6-10 windows, BROLL_VISION_CAP default 16)
        → broll-composite              (full-frame hard-cut cutaways onto the vertical clip, saliency-cropped not center; podcast audio continuous, no transition SFX by default — BROLL_SFX=1 re-enables a whoosh on each cutaway in/out)
        → burn-subtitles               (chunk-karaoke PNG overlay, RMS-aligned, burned ON TOP of the b-roll)
        → sfx-beats (comedy)           (Claude marks punchline/irony/insight beats → vine boom / record scratch / ding; zero beats on non-comedic clips → passthrough; SFX_COMEDY=0 skips)
        → generate-title + title-transition (Claude title ≤7 words ALL-CAPS → animated COLD-OPEN title in the span's title_style, rendered in the TOP banner over the LIVE opening footage — no blocking card, no SFX — held until TITLE_SWAP then handed off to the source citation)
        → brand-overlays               (source-credit TOP chyron y≈4%, fading IN at TITLE_SWAP so the cold-open title owns the top banner first + @C0BALT_CUT watermark y≈97.5% composited in ONE ffmpeg pass; falls back to the standalone source-credit → watermark two-pass path)
        → loudnorm                     (two-pass to -14 LUFS / -1.5 dBTP)
        → like-subscribe-overlay       (branded CTA — gem avatar + @C0BALT_CUT — ~4s within the FIRST THIRD of the clip + bell SFX)
        → pick-mood + bg-music         (Claude picks ./songs/<mood>/ from clip transcript; bed at ~-18dB, last 5 picks blacklisted via ./songs/.recent)
        → qc-clip                      (ffprobe gate: duration 15-90s, size >100KB)
        → name-short + save-local      (title → kebab-case filename → ./output/<source-slug>/<title-slug>.mp4)
  └─ broll-cleanup     (ONCE at end of run: evict only this run's mcptube b-roll ingests + local broll/* cache; broll_plan.json persists)
```

**Hard rules for any "rerun the pipeline" / full-pipeline request:**
- Use `fill-vertical` for the 9:16 reframe — punch-in crop that FILLS the frame (face ~45% height, lip-activity speaker pick, saliency crop for no-face shots). NEVER letterbox, NO blur bars. Both `fit-vertical` and `reframe-vertical` are retired/deleted (they linger only in the gitignored stale `.agents/` copy — never resurrect them). It clusters faces across shots to find the dominant speaker, biases the per-shot pick toward whoever is actually talking, and frames a non-speaking reaction/listener shot LOOSER so the short never dwells hero-framed on the wrong person.
- pick-segments builds each short from `cuts` — 1-3 NON-contiguous source ranges within ONE topic, assembled into one story (skip the sag, keep hook→payoff). The `cut-clip` step cuts each range precisely and concats; `assemble.py` joins the clip-local transcript so all downstream skills stay synced. A single-cut short is `cuts:[[t0,t1]]` and takes the plain `rebase.py` path. Multi-cut spans bypass verify-coherence tightening (already tightened by construction).
- pick-segments must choose complete cold-viewer story arcs, not isolated replay highlights. YouTube replay heatmap and RMS are supporting evidence only: use them to discover candidates and break close ties, but never let them outrank setup → turn → landing context. A replay spike often marks the memorable sentence inside a larger explanation; include enough before and after for the clip to make sense and not end abruptly.
- `verify-bookends` runs AFTER `tighten-pace` and BEFORE `fill-vertical`. It is INWARD-ONLY (bookend-trim already had its outward chance) and may drop a span only on cleanliness failures requiring >2s of trim — never on hook weakness alone. Disable with `VERIFY_BOOKENDS=0`.
- `verify-completeness` runs AFTER `bookend-trim` and BEFORE `cut-clip`, in SOURCE coordinates. It is the OUTWARD counterpart to verify-bookends: it reads each span's assembled arc (the words inside its `cuts`) plus a tail lookahead and may nudge `t1`/the last cut's end outward to the landing sentence (capped at dmax) when the payoff got cut off. It NEVER drops a span and NEVER extends past dmax. It runs pre-cut because the clip-local transcript discards source timestamps after cut/trim/tighten (rebase.py), so outward extension is only clean in source coords. Non-fatal (passthrough on any failure), idempotent, `VERIFY_COMPLETENESS=0` disables.
- `chunk-captions` runs BEFORE `broll-pick` (b-roll windows snap to whole caption-chunk boundaries — no mid-word cuts).
- `broll-composite` runs AFTER `broll-pick` and BEFORE `burn-subtitles` — captions must burn OVER the cutaways, never under them.
- B-roll cutaways are full-frame hard cuts (entire 1080×1920 replaced, scale-cover + SALIENCY crop toward the action — not blind center — no bars, no crossfade/zoom). Podcast audio is CONTINUOUS — never replaced; no transition SFX by default (pure stream-copy), `BROLL_SFX=1` amix's a short synthesized whoosh onto each cutaway in/out. B-roll audio is always dropped. Bottom-bar/letterbox b-roll = regression.
- `broll-pick` anchors are CONTEXTUAL/scene-level, not literal keyword objects — footage must match the story's tone (a tense "red dot" beat wants a sniper/laser sight, NOT a cat laser toy). Vision verify is given the spoken context and rejects literal-but-wrong matches. Aim dense (~6-10 windows where a sensible visual exists). B-roll files are namespaced per clip (`<clip>_broll_NN.<ext>`) in the shared `broll/` dir — NEVER reuse bare `broll_NN.mp4` slot names across spans (cross-span contamination bug).
- `broll-pick` discovery uses the mcptube-bundled `yt-dlp` ytsearch, NOT `mcptube discover` (the latter needs an LLM API key the stack forbids). Vision verify via Claude; candidate prep (ingest + frame grids) runs CONCURRENTLY and verification is BATCHED — up to `BROLL_BATCH` (default 4) candidates judged per vision round-trip, with `BROLL_VISION_CAP` (default 16) bounding total candidates judged, not calls. Each window gets at most 2 query attempts (original + one literal↔metaphorical rewrite; rewrites are also batched into one call).
- `broll-cleanup` runs exactly ONCE at end of run, evicting only `video_id`s in each `broll_plan.json`'s `ingested_video_ids` — never the podcast source. It must never modify or delete `broll_plan.json`.
- `title-transition` is mandatory and runs AFTER `burn-subtitles`, BEFORE the brand overlays. It is a COLD OPEN, NOT a card: the styled title animates in the TOP banner zone (anchor `TITLE_ANCHOR_FRAC`, default 0.135) OVER the live opening footage so frame 1 is content (a face mid-sentence), never a blocking title card — this is the swipe-rate / "Stayed to Watch" fix. NO SFX (the card-era riser/boom is retired) and NO full-frame bg treatment (the old flash/shake/dim shook the live shot). The title holds until `TITLE_SWAP` (default 2.0s, the per-style `dur`) and clears via its own fade-out; `brand-overlays` (and the standalone `source-credit` fallback) then fade the source citation INTO that same top slot at `TITLE_SWAP` so the two time-share the banner. The title text comes from `generate-title`; the animation style comes from the span's `title_style`, assigned by `pick-title-styles` (default `slam` when absent). Five styles — slam (hype), typewriter (true crime), glitch (tech), bounce (comedy), cinematic (documentary) — each a PIL frame sequence. A sixth `news` style was prototyped and CUT after review — do not resurrect it. `pick-title-styles` is best-effort/non-fatal: on any failure spans fall back deterministically and the run continues.
- `bookend-trim` runs AFTER `verify-coherence` and BEFORE `cut-clip`. It snaps each span's `[t0, t1]` to a clean sentence boundary so shorts don't end mid-sentence (whisper output has punctuation stripped, so Claude infers boundaries — heuristics on `.!?` won't work).
- `like-subscribe-overlay` runs AFTER `loudnorm` and BEFORE `bg-music`. It overlays a branded animated CTA (channel gem avatar + @C0BALT_CUT handle + subscribe/like/bell choreography) for ~4s WITHIN THE FIRST THIRD of the clip — start clamped so the CTA ends by the 1/3 mark, floored after the ~2.5s title card — so viewers who drop off early never miss it. `like-subscribe-overlay.sh <in> <out> [dur=4.0] [pos=0.15]`.
- `brand-overlays` runs AFTER `title-transition` and BEFORE `loudnorm`. It bakes BOTH persistent brand marks in one encode: the "Original video: <title>" credit as a TOP chyron (banner top at y≈4%, title read from `work/<id>/ingest.json`, clear of the lower-third captions and the centered title card) and the `@C0BALT_CUT` channel mark bottom-center (bottom-anchored at y≈97.5% — the vertical opposite). Brand colors from `brand/BRAND.md`: Platinum `#E8ECF1` type with the slashed-zero in Sapphire Glow `#2E6BFF`. The CTA overlay composites on top of the watermark for ~4s within the first third, which is intended. The standalone `source-credit` and `watermark` skills remain the single-overlay atomic ops (and the orchestrator's fallback path) and own the PNG renderers brand-overlays reuses.
- The caption/accent blue everywhere (burn-subtitles active word, title-transition accent word, source-credit label, watermark zero, CTA accent) is Sapphire Glow `#2E6BFF` from `brand/BRAND.md` — matched to the channel pfp/banner gem. Electric cyan `#00E5FF` is retired; reintroducing it is a regression. All overlay text is Impact (`/System/Library/Fonts/Supplemental/Impact.ttf`) with a thick black stroke.
- Final shorts are named from the title: `name-short` slugs `generate-title`'s output into `<kebab-title>.mp4`, and `save-local` puts it in `output/<source-title-slug>/`. Generic `short_NN.mp4` names in output/ = the orchestrator forgot to pass the name through.
- If `start.sh`/`shorts.sh` does not invoke every skill above in the listed order, the entrypoint is wrong — fix the entrypoint, do not silently skip skills.
- Verify after a run: every saved `output/<source-slug>/*.mp4` must be 1080x1920 (full-bleed punch-in, NO blur bars), open with a COLD-OPEN top-banner title over live footage for ~2s (NOT a blocking centered card, NO title SFX) that hands off to the source citation, AND have a CTA card for ~4s landing within the first third of the clip. If any is missing, the pipeline regressed.
- `zoom-punch` runs AFTER `fill-vertical` and BEFORE `broll-pick`/`broll-composite`/`burn-subtitles` — cutaways replace the full frame and captions must not wobble, so the punch zooms only ever touch the clean vertical. Deterministic (no Claude), non-fatal (failure → unzoomed passthrough), `ZOOM_PUNCH=0` disables.
- `sfx-beats` comedy mode IS canonical: it runs AFTER `burn-subtitles` and BEFORE `generate-title`/`title-transition`. Claude marks 0-4 punchline/irony/insight beats (vine boom / record scratch / ding); marking ZERO beats on a non-comedic clip is correct behavior and passes through. Non-fatal, `SFX_COMEDY=0` disables. The tension mode (riser/hit/stinger) stays NOT canonical — only on request.
- `SHORTS_DMIN`/`SHORTS_DMAX` default to 28/55 (June 14 re-tune from 20/40, which had over-truncated). These are the SOURCE-SELECTION budget, NOT the delivered runtime: pick-segments selects generously within them and downstream trim-filler/tighten-pace/verify-bookends shave ~20-30%, landing the DELIVERED short in the ~30-40s sweet spot. The 40→55 history: June 12's Growth suite dropped 60→40, but combined with the downstream cutters that delivered ~26-32s ("truncated" feeling); 55 restores complete-feeling arcs without resurrecting the dead 60s back-half. Override per-run when a story truly needs more room.

## work/<id>/ Artifact Map

Every source gets `work/<sha1(url)[:10]>/`. Source-level files:

| File | Written by | Contents |
|---|---|---|
| `source.mp4`, `ingest.json` | ingest | video + `{id, url, title, duration, fps, width, height, path}` |
| `heatmap.json` | ingest | `{heatmap:[{start_time,end_time,value}], chapters:[...]}` — YouTube most-replayed graph (absent on low-view sources; backfilled on cache-hit) |
| `transcript.json` | transcribe | `{source, language, words:[{t0,t1,w}], segments:[{t0,t1,text}]}` |
| `topics.json` | segment-topics | `{topics:[{t0,t1,title,summary}]}` |
| `candidates.hint.json` | segment-topics (rlm path only) | `{candidates:[{t0,t1,quote,why}]}` — clip-moment discovery hints from the full-resolution per-chunk read; consumed by pick-segments as a HINT (absent on the single-prompt path) |
| `segments.raw.json` | pick-segments | `{shorts:[{t0,t1,cuts,topic,rationale,title_suggestion,hook_score,structure_score,overall_score,replay_quotient?}]}` |
| `segments.coherent.json` | verify-coherence | same + `coherence_verdict`/`coherence_note` |
| `segments.json` | bookend-trim + verify-completeness + pick-title-styles | final spans + `bookend_note` + `completeness_verdict`/`completeness_note` + `title_style`/`title_style_note` (in start.sh verify-completeness runs per-span in phase 2, not on this source-level file) |
| `broll/` | broll-pick | downloaded cutaways `<clip>_broll_NN.<ext>` (evicted by broll-cleanup) |
| `_pane/` | pane.sh | per-step `in.txt`/`out.txt`/`out.done` for tmux Claude dispatch |

Per-span files chain as `clip_NN.<stage>`: `.mp4` (cut) → `.transcript.json` (rebased) → `.keeps.json` + `.trim.mp4` + `.trim.transcript.json` (filler cut) → `.tight.mp4` + `.tight.transcript.json` (pace) → `.verify.json` (bookends verdict) → `.vert.mp4` (9:16) → `.zoom.mp4` (punch-ins) → `.chunks.json` → `.broll_plan.json` + `.brolled.mp4` → `.sub.mp4` (captions) → `.sfx.mp4` (comedy SFX) → `.title.txt` + `.titled.mp4` → `.marked.mp4` (brand-overlays; a `.credited.mp4` intermediate appears only on the two-pass fallback) → `.leveled.mp4` (loudnorm) → `.ctaed.mp4` → `.mood.txt` + `.final.mp4` (music). Multi-cut spans also leave `clip_NN.cut_JJ.mp4` pieces + `clip_NN.cuts.txt` concat list.

**Sidecars:** `.*meta` files (`.tfmeta`, `.tpmeta`, `.ttmeta`, `.vbmeta`, `.scmeta`, `.bometa`, `.lsmeta`, `.bgmeta`, `.pickmeta`, `.compmeta`, `.zpmeta`, `.sfxmeta`) are mtime+param cache signatures — every skill is idempotent and skips when output is newer than inputs and the signature matches. `.path` files (`vert.path`, `ctx.path`, `leveled.path`) hand artifact locations between start.sh phases. `clip_NN.fail*` / `clip_NN.done.completion` are phase failure/resume markers.

## Claude Dispatch (pane.sh)

`_lib/pane.sh` provides `run_claude_step <step> <prompt> <reply>`: with no `SHORTS_PANE` it runs `claude -p --output-format text`; with `SHORTS_PANE=<tmux-session>` + `SHORTS_PANE_MODE=chat` (what start.sh uses) it messages a long-lived interactive Claude pane, which writes `out.txt` + touches `out.done`, polled every `PANE_TICK` (6s) up to `PANE_TIMEOUT` (1800s). Claude-driven skills all follow the same shape: `build_prompt.py` → `run_claude_step` → `parse_reply.py` (with a deterministic fallback if the reply doesn't parse).

## Environment

`.env` holds source-of-truth paths (never hardcode): `WHISPER_BIN`, `WHISPER_MODEL`, `OUTPUT_DIR`. Runtime knobs: `SHORTS_N` / `SHORTS_DMIN` / `SHORTS_DMAX` (span count + source-selection duration bounds; defaults 5 / 28 / 55), `SHORTS_MAX_PAR` (parallel spans, default 1), `SHORTS_ENCODER` (`videotoolbox`|`x264`) via `_lib/encode.sh`, `BROLL_VISION_CAP` (default 16, counts candidates judged) / `BROLL_BATCH` (candidates per vision call, default 4), `BROLL_PICK=0` / `VERIFY_BOOKENDS=0` / `VERIFY_COMPLETENESS=0` / `ZOOM_PUNCH=0` / `SFX_COMEDY=0` / `BROLL_SFX=0` (disable those steps), `RLM_TOPICS` (`1` forces rlm-assisted segment-topics, `0` forces single-prompt; unset = auto above `RLM_TOPICS_MIN_SEC`, default 1500s) / `RLM_TOPICS_CHUNK_SEC` (rlm chunk window, default 600s), `TITLE_SWAP` (cold-open title hold / citation hand-off point in seconds, default 2.0; shared by title-transition + brand-overlays + source-credit) / `TITLE_ANCHOR_FRAC` (title top-banner vertical anchor as a fraction of height, default 0.135), `MCPTUBE_URL` (default `http://127.0.0.1:9093/mcp`), `PANE_TICK` / `PANE_TIMEOUT`, `SCOUT_PER_QUERY` / `SCOUT_SHORTLIST` / `SCOUT_MIN_VIEWS` / `SCOUT_DUR_MIN` / `SCOUT_DUR_MAX` (scout-sources).

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
├── start.sh                   # PRIMARY entrypoint — tmux pane orchestrator (srcprep/analysis + per-span lanes), resumable
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
├── demos/title-styles/        # demo.sh renders all 5 title styles on any clip (out/ gitignored)
├── work/<id>/                 # per-source working dirs (see Artifact Map above)
├── work/_scout/               # scout-sources output (candidates.json — what to clip next)
├── output/<source-slug>/      # finished shorts, <title-slug>.mp4
├── .agents/                   # STALE gitignored copy of old skills (has retired fit-vertical/reframe-vertical) — never edit
└── .claude/
    ├── commands/start.md      # /start command definition
    ├── crew/ralph/            # ralph crew-member identity (CLAUDE.md, BIO.md, state-*.json)
    └── skills/
        ├── _lib/pane.sh       # run_claude_step: claude -p vs tmux-pane dispatch + polling
        ├── _lib/encode.sh     # vt_args/vt_threads: VideoToolbox vs libx264 encoder args
        │   # — selection phase —
        ├── scout-sources/     # scout-sources.sh + score.py + niches.txt: PRE-pipeline outlier discovery → work/_scout/candidates.json (keyless yt-dlp, no Claude)
        ├── ingest/            # ingest.sh: yt-dlp → source.mp4 + ingest.json + heatmap.json (most-replayed graph)
        ├── transcribe/        # transcribe.sh: whisper.cpp → word-level transcript.json
        ├── segment-topics/    # segment-topics.sh + build_prompt/parse_reply.py: Claude topic chapters; + build_rlm_prompt/parse_candidates.py: rlm-assisted map-reduce path (chunk → rlm-subcall per chunk → synthesize topics.json + candidates.hint.json) when RLM_TOPICS / duration threshold
        ├── pick-segments/     # pick-segments.sh + rms.py + build_prompt/parse_reply.py: Claude span picks w/ cuts + hook scores + replay-heatmap prior + candidates.hint.json discovery hint
        ├── verify-coherence/  # verify-coherence.sh: Claude keep/tighten gate per span
        ├── pick-title-styles/ # pick-title-styles.sh + build_prompt/parse_reply.py: ONE batched Claude call assigns title_style per span (fit > variety > recency; .recent log gitignored)
        ├── bookend-trim/      # bookend-trim.sh + trim.py: Claude sentence-boundary snap (±6s)
        ├── verify-completeness/ # verify-completeness.sh + build_prompt/parse_reply.py: arc-completeness gate (complete|needs_more_tail|truncated; nudges t1 outward to the landing within dmax; source coords, after bookend-trim before cut-clip; VERIFY_COMPLETENESS=0 disables)
        │   # — per-span edit phase —
        ├── cut-clip/          # cut-clip.sh: ffmpeg [t0,t1] trim (stream-copy or reencode)
        ├── trim-filler/       # trim-filler.sh: Claude marks filler → keeps.json + trimmed transcript
        ├── cut-filler/        # cut-filler.sh: ffmpeg select/aselect applies keeps.json
        ├── tighten-pace/      # tighten-pace.sh + plan.py: collapse gaps >0.18s → 0.08s (0.15s after sentences)
        ├── verify-bookends/   # verify-bookends.sh: Claude VISION gate on head/tail 1.5s (keep/trim/drop, inward-only)
        ├── fill-vertical/     # fill-vertical.sh + fill_vertical.py + models/face_landmarker.task: punch-in 9:16 (MediaPipe faces, lip-activity speaker pick, OpenCV saliency fallback)
        ├── zoom-punch/        # zoom-punch.sh + plan.py: ~10% punch-in pulses at RMS-peak words (deterministic, after fill-vertical)
        │   # — captions & b-roll phase —
        ├── chunk-captions/    # chunk-captions.sh: Claude groups words into 3-6-word caption chunks
        ├── broll-pick/        # broll-pick.sh + pick_anchors/parse_anchors/verify_batch_prompt/parse_verify_batch/emit_plan.py: anchors → yt-dlp ytsearch → concurrent mcptube prep → BATCHED Claude vision verify → broll_plan.json (verify_prompt/parse_verify.py = legacy single-candidate versions)
        ├── broll-composite/   # broll-composite.sh + build_filter.py + make_whoosh.py: full-frame hard-cut overlays, saliency crop, whoosh on each cut
        ├── broll-cleanup/     # broll-cleanup.sh: end-of-run mcptube + broll/ cache eviction
        ├── burn-subtitles/    # burn-subtitles.sh + burn_subtitles.py: PIL PNG karaoke (Impact, Sapphire active word, RMS-aligned)
        │   # — finishing phase —
        ├── generate-title/    # generate-title.sh: Claude ≤7-word ALL-CAPS third-person title
        ├── title-transition/  # title-transition.sh + styles.py + sfx.py: styled intro card (slam/typewriter/glitch/bounce/cinematic) as PNG frame sequence + synthesized SFX bed
        ├── brand-overlays/    # brand-overlays.sh: credit + watermark PNGs in ONE ffmpeg pass (canonical; reuses the two renderers below)
        ├── source-credit/     # source-credit.sh + render_credit.py: top chyron "Original video: <title>" (y≈4%) — standalone/fallback
        ├── watermark/         # watermark.sh + render_watermark.py: @C0BALT_CUT bottom mark (y≈97.5%) — standalone/fallback
        ├── loudnorm/          # loudnorm.sh: two-pass ffmpeg loudnorm to -14 LUFS / -1.5 dBTP
        ├── like-subscribe-overlay/  # like-subscribe-overlay.sh + cta.html + build-cta.sh: branded alpha ProRes CTA (gem avatar + @C0BALT_CUT, ~4s within the first third) + bell SFX
        ├── pick-mood/         # pick-mood.sh: Claude picks songs/<mood>/ from clip transcript
        ├── bg-music/          # bg-music.sh: looped bed, vol 0.17 (~-18dB), .recent blacklist
        ├── sfx-beats/         # sfx-beats.sh + plan_sfx/comedy_prompt/parse_comedy/make_sfx.py: comedy mode (boom/scratch/ding on Claude-marked beats — CANONICAL after burn-subtitles) + tension mode (riser/hit/stinger — on request only)
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
