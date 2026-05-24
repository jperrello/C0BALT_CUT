# Shorts Pipeline Quality Pass — Spec

## Working definition

Four targeted changes to the existing atomic-skills shorts pipeline (not a new project) to fight quality regressions in the rendered shorts:

1. A coherence pass that prevents single shorts from containing two unrelated topics.
2. A title card visual rework that re-unifies the title with the burned subtitles.
3. A title text rework with a principles-based prompt for third-person, engagement-driven titles.
4. A subtitle rework that replaces the rolling 4-word window with discrete phrase chunks that swap as whole units.

**This is not:** a rewrite of the pipeline shape, a change to the skill contract, a removal of `segment-topics`, or a new long-lived `/crew` member. Every change lives as an edit-or-add inside `.claude/skills/<name>/`, with JSON files moving between skills as before.

## Who uses it and how

The pipeline operator runs `shorts.sh <url>`. The pipeline ingests, transcribes, finds topical boundaries, picks N spans, **verifies each span is coherent and tightens any that aren't**, then per surviving span: cuts, fits to 9:16, **chunks captions into phrase units via Claude**, burns subtitles with the new chunk-based rendering, **generates a hook-driven third-person title per clip**, renders the title card matched to caption style, loudnorms, QCs, and saves to `./output/<source>/`.

## Core features

- **`verify-coherence` (new skill)** runs after `pick-segments`. For each picked span, Claude reads only that span's transcript slice and verdicts `keep` / `tighten`. On `tighten`, returns a trimmed `[t0, t1]` covering only the dominant topic.
- **`segment-topics` (reworked)** produces finer-grained topic boundaries so `pick-segments` has less room to cross them. (Tighter prompt — same I/O contract.)
- **`chunk-captions` (new skill)** runs before `burn-subtitles`. Reads the clip-local transcript, calls Claude to return an ordered list of `{text, words:[{w,t0,t1}]}` chunks where each chunk is a self-contained phrase. Writes `chunks.json`.
- **`burn-subtitles` (reworked)** consumes `chunks.json` instead of raw word stream. Renders one chunk on screen at a time as a single overlay; chunks hard-cut to the next at the boundary; within a chunk, the active word lights cyan as the speaker hits it (karaoke preserved).
- **`generate-title` (new skill, split out of `pick-segments`)** runs per clip. Reads the clip's transcript + `ingest.json` metadata; Claude infers the subject and emits an ALL-CAPS, ≤7-word, third-person, hook-driven title. Writes the title string.
- **`title-transition` (reworked)** restyles the card to match captions: Impact font, white fill with cyan accent treatment, ALL CAPS — same visual language as the burned subtitles.

## Rules and edge cases

- **Tightened spans below `dmin`** are dropped silently. The pipeline produces fewer shorts rather than rendering a too-short one.
- **`verify-coherence` returns `keep` on ambiguity.** Default to trusting `pick-segments`; only tighten when the topical jump is clear in the transcript.
- **Subject inference per clip.** Each call to `generate-title` re-infers the subject from that clip's transcript + `ingest.json` (title, uploader). A guest-focused span can name the guest even if other shorts from the same source name the channel host.
- **Title voice — principles only, no template.** Prompt rules: third-person, name the subject, promise a specific moment or behavior, ≤7 words, ALL CAPS, no clickbait emoji, no first-person, no questions. Claude picks angle and phrasing per clip.
- **Chunk-captions chunk size** is Claude's call — no hard cap. Prompt guides toward "what one breath / one clause would naturally hold," typically 3–6 words. The skill validates that every word in the clip transcript appears in exactly one chunk and that chunk timestamps are monotonic; otherwise it fails loudly.
- **Within-chunk karaoke** continues to use the existing color preset: white base, cyan `#00E5FF` active word, Impact font.
- **Chunk swap is a hard cut.** No fade, no slide.
- **Title card length safety:** the ≤7-word cap is enforced in `generate-title`; `title-transition` keeps its existing auto-shrink as a second safety net.

## Look and feel

Single visual language across the short. Both the opening title card and the running captions use Impact, ALL CAPS, white with cyan accents — viewers should not perceive the title and the captions as belonging to different videos. The new chunked captions feel percussive: a phrase appears, the active word lights up as it's spoken, the phrase vanishes the instant the next one begins. No scrolling, no sliding, no overlap between chunks.

## Resolved decisions

### Coherence fix placement
Choice: Both — tighten `segment-topics` AND add `verify-coherence` as a post-pick gate.
Why: User explicitly chose "belt and suspenders" — tighter boundaries upstream catch most cases, the gate catches what slips through.

### Failure mode for incoherent spans
Choice: Tighten in place (trim to dominant topic).
Why: User picked this over drop/replace and silent drop. Preserves clip throughput; if a tightened span falls below `dmin`, it's dropped silently per the edge-case rule.

### Title card visual treatment
Choice: Exact match — Impact, cyan + white, ALL CAPS.
Why: User chose "Exact match" for one visual language across the short. Accepted the coupling cost.

### Title voice prescriptiveness
Choice: Principles only — no template, no opener menu.
Why: User picked "principles only — let Claude pick the angle". Maximum per-clip variety.

### Subject name source
Choice: Inferred per-clip from clip transcript + `ingest.json`.
Why: User combined transcript inference with ingest.json metadata and chose per-clip scope.

### Subtitle chunk-boundary rule
Choice: Claude-generated chunking via a new `chunk-captions` skill.
Why: User picked this over pause-driven, punctuation+cap, and hybrid options. Highest semantic quality.

### Within-chunk behavior
Choice: Karaoke highlight inside the chunk (active word cyan).
Why: Preserve karaoke energy; the fix is killing the scroll, not killing the highlight.

### Chunk swap visual
Choice: Hard cut.
Why: Snappiest, matches TikTok caption feel.

### Title length and case
Choice: Hard cap ≤7 words, ALL CAPS.
Why: Forces punchy hook-style titles and keeps visual unity with all-caps captions.

### `generate-title` as its own skill
Choice: Split title generation out of `pick-segments` into a new `generate-title` skill.
Why: Atomicity rule in `CLAUDE.md` — "One atomic operation per skill." Title generation now has real prompt logic (subject inference, voice principles, length cap).

## Technical constraints

- Skills live under `.claude/skills/<name>/` with `SKILL.md` frontmatter contract; one atomic op per skill.
- Inter-skill data is JSON files on disk.
- Claude is invoked from the host session (`claude -p`) per the existing pattern in `pick-segments` / `segment-topics`.
- `shorts.sh` invokes the new order: `… pick-segments → verify-coherence → per-span(cut-clip → fit-vertical → chunk-captions → burn-subtitles → generate-title → title-transition → loudnorm → qc-clip → save-local)`.
- All visual changes use the existing PNG-overlay rendering path (local ffmpeg has no libass/drawtext).

## Out of scope

- Cross-short de-duplication.
- Re-enabling `pick-speaker` / `reframe-vertical` speaker-tracking crop; canonical chain stays on `fit-vertical`.
- Audio/SFX changes; `sfx-beats` and `loudnorm` are unchanged.
- A long-lived `/crew` tmux member.
- Configurable subject-name override via CLI flag.

## Decisions to double-check

- **Tightening below `dmin` silently drops the clip.** If frequent in practice, switch to a "request replacement" loop.
- **Per-clip subject inference can name different subjects across shorts from one source.** If inconsistent in practice, switch to per-source caching with override.
