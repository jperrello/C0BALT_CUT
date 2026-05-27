# May 26 — Multi-part Spec

This file collects multiple independent spec sections drafted over the course of 2026-05-26, to be released together in one overseer session.

---

## 1. Pipeline orchestration via parallel tmux crews

### Working definition
A new top-level entry point (`/start <url-or-source-id>`) that fans the existing shorts pipeline out across several long-lived tmux Claude panes plus bash panes, so the user can attach to any pane mid-run and watch the actual Claude reasoning (or ffmpeg output) instead of opaque `claude -p` subprocesses. Each pane owns a *phase* of the pipeline; the orchestrator drives panes via `tmux send-keys` and waits on sentinel files. Per-span work fans out in parallel — N spans means N editor panes, N captions panes, and N broll-pick panes running simultaneously. All inter-skill data continues to pass as JSON on disk under `work/<id>/`; this is an orchestration change, not a data-flow change.

### Who uses it and how
User-facing surface is one slash command: `/start <youtube-url>` or `/start <source-id>` (when the video is already ingested). The orchestrator prints overall progress to the foreground; the user can `tmux attach -t <pane>` at any time to inspect a specific phase. On run completion, all panes are torn down.

### Phase layout

**Phase 1 — Source prep (two parallel panes):**
- `pane: src-prep` (bash) — `ingest` → `transcribe`
- `pane: crew-analysis` (Claude) — `mcptube add <url>` (registers source with the local mcptube server), then once `transcript.json` exists: `segment-topics` → `pick-segments` → `verify-coherence`. The pane has the mcptube MCP server available so Claude can call `search`, `ask`, `frame-query`, and `classify` against the source video while picking segments. `bookend-trim` moves OUT of phase 1 (see phase 2).

The analysis pane starts in parallel with `src-prep` and uses mcptube tools against the raw URL before the local transcript is ready; once `transcript.json` lands it switches to the Claude reasoning chain.

**Phase 2 — Editor (one Claude pane per span, all spans in parallel):**

Per span `i`, pane `crew-editor-i` runs:
1. `bookend-trim` (Claude) — decides clean clip end points from sentence boundaries. Moved here because end-point selection is part of editing intelligence, not source prep.
2. `cut-clip` + `rebase` (bash)
3. `trim-filler` (Claude, after `clear-and-talk` reset of the pane) — Claude reasons about which inter-word gaps and asides to remove so the short has punchy jump cuts. This is the engagement-driver: Claude is heavily involved in deciding cut/resume, not just hunting umms.
4. `cut-filler` + `tighten-pace` + `fit-vertical` (bash)

Two distinct Claude reasoning jobs (`bookend-trim`, `trim-filler`) inside one pane, separated by `clear-and-talk` so each starts with a clean context window.

**Phase 3 — Captions+title and broll-pick in parallel (two panes per span):**

Per span `i`, in parallel:
- `pane: crew-captions-i` (Claude) — `chunk-captions` → `burn-subtitles` (bash) → `clear-and-talk` → `generate-title` → `title-transition` (bash) → `loudnorm` (bash)
- `pane: crew-broll-i` (Claude) — `broll-pick` (new split, see section 2). Picks Pexels clips against the phase-2 `fit-vertical` output + transcript; emits `broll_plan.json`. Does NOT composite.

Both panes consume the phase-2 `fit-vertical` clip; they write disjoint output files so they don't collide.

**Phase 4 — Completion (one bash pane per span, all spans in parallel):**

Per span `i`, pane `completion-i`:
1. `broll-composite` (bash, ffmpeg) — overlays the picked broll clips onto the loudnorm output using `broll_plan.json`.
2. `like-subscribe-overlay` (bash)
3. `bg-music` (bash)
4. `qc-clip` (bash)
5. `save-local` (bash)

Panes are named deterministically (`shorts-<source-id>-<phase>-<i>`) so attaching is predictable. Panes torn down at end of run; no reuse across `/start` invocations.

### Core features
- **Preflight check.** `/start` first verifies the mcptube MCP server is reachable at `http://127.0.0.1:9093/mcp` (HTTP probe; 406 on GET is healthy). If unreachable, prints how to start it (`mcptube serve`) and aborts before spawning panes.
- **Single slash command surface.** `/start <url|source-id>` is the only user entry point; `shorts.sh` is retained as a non-interactive fallback.
- **Orchestrator-driven tmux.** Orchestrator writes prompt files under `work/<id>/_pane/<pane>/in.txt`, sends `cat <path> | claude` (or skill bash) to the pane via `send-keys`, waits on `out.done` sentinel, reads `out.txt`. Skill `.sh` wrappers gain a "drive an existing Claude pane" mode for the 8 Claude-driven skills (`segment-topics`, `pick-segments`, `verify-coherence`, `bookend-trim`, `trim-filler`, `chunk-captions`, `generate-title`, `broll-pick`). Headless `claude -p` mode is retained as a fallback.
- **clear-and-talk between unrelated Claude jobs in the same pane.** Editor pane runs bookend-trim → clear-and-talk → trim-filler; captions pane runs chunk-captions → clear-and-talk → generate-title. Prevents context leak between unrelated reasoning jobs.
- **Progress visible from foreground.** Orchestrator prints `[phase 2 / span 3] trim-filler running…` style lines; user can attach for detail.

### Rules and edge cases
- **Analysis pane finishes before transcript ready:** mcptube MCP calls (which work off the URL) can complete before whisper finishes; the pane idles waiting for `transcript.json`, then resumes with `segment-topics`. No timeout — whisper-cli on a long source can take minutes.
- **A span fails in phase 2:** mark span as skipped, do NOT spawn its phase 3 / 4 panes. Other spans continue. Surface in final summary.
- **A span fails in phase 3 captions but broll-pick succeeded (or vice versa):** drop the whole span at the phase 3/4 boundary; completion pane is not spawned. broll_plan.json is left on disk for debugging.
- **User attaches to a pane mid-run:** safe. Pane shows the live Claude session or bash output; detaching does not interrupt work. `send-keys` continues to drive the pane.
- **`/start <source-id>` for already-ingested video:** skip ingest+transcribe in src-prep if `source.mp4` and `transcript.json` already exist (existing skill-level caching). crew-analysis still runs mcptube `add` (idempotent) and the picking chain.
- **Re-running `/start` on a source that already has shorts under `output/`:** existing shorts are overwritten. No `--force` flag needed; if the user said `/start`, they want a fresh run.
- **Parallelism bound by host:** 5 spans × multiple panes = 20+ concurrent Claude processes is heavy on a laptop. The orchestrator does NOT auto-throttle in v1 — if the user wants a smaller fan-out, they pass `n=2`. Worth instrumenting and adding a `--max-parallel` knob in a follow-up if real runs OOM.

### Resolved decisions

#### How to drive Claude inside a pane
Choice: orchestrator writes prompt to file, `tmux send-keys` a shell command into the pane that reads the file and pipes to `claude`, waits on a sentinel file the pane writes when done.
Why: the user picked the "tmux send-keys / sentinel" alternative over rewriting every skill to embed a long-running Claude pane driver. It keeps the orchestrator as the single source of state and avoids each pane needing its own loop daemon.

#### Per-span parallelism
Full fan-out chosen over serial spans — prioritizes wall-clock speed over pane manageability. Deterministic pane names preserve attach-and-inspect for any span.

#### Where bookend-trim lives
Phase 2 (editor), not phase 1. Deciding where a clip should end is editing intelligence — same judgment as deciding which gaps to cut, belongs alongside trim-filler. Phase 1's crew-analysis stops at verify-coherence and hands off span candidates without locked endpoints.

#### Rewriting the 8 Claude-driven skill .sh wrappers
Add a "drive existing pane" mode to each; retain headless `claude -p` fallback. Dual mode keeps the non-interactive path alive for CI or scripted runs without blocking the interactive `/start` UX.

#### mcptube as a hard dependency
Preflight check; abort if unreachable. Phase 1's analysis pane uses mcptube MCP tools (`search`, `ask`, `frame-query`, `classify`) to enrich pick-segments with vision-grade context. Silently degrading would hide a regression in pick quality.

#### broll split prerequisite
Ship `broll-pick` / `broll-composite` split as part of this work. The vision-verification work in section 2 already restructures the picking logic; splitting picking from compositing at the same time avoids touching the skill twice. See section 2 for the split details.

### Look and feel
No change to rendered output. This is purely an orchestration / observability refactor — the user sees the same shorts under `./output/<source>/short_NN.mp4`, but during the run can `tmux attach` to any pane and watch Claude's reasoning live instead of staring at a single bash log.

### Technical constraints
- mcptube MCP server must be reachable at `http://127.0.0.1:9093/mcp` (configurable via env var `MCPTUBE_URL`, default the local address).
- `tmux` ≥ 3.0 (already a host requirement for `/crew`).
- The 8 Claude-driven skill `.sh` wrappers gain a `--pane <name>` mode that drives an existing tmux pane via send-keys + sentinel files. Without `--pane`, behavior is unchanged (`claude -p`).
- Sentinel files live under `work/<id>/_pane/<pane>/`. Pane stdout is also tee'd to `work/<id>/_pane/<pane>/log` for post-run debugging.
- Orchestrator process exits cleanly on failure: kills outstanding panes, prints which span failed where, leaves intermediate JSON on disk for inspection.
- No new MCP servers beyond mcptube. No new Python dependencies.

### Out of scope
- Reusing panes across `/start` invocations.
- Throttling / max-parallel limits on per-span fan-out (deferred; add when a real run OOMs).
- Replacing `shorts.sh` (kept as a non-interactive fallback).
- A web UI or non-tmux orchestrator backend.
- Changing the per-skill data contracts. All JSON files on disk keep their current shapes.
- Adding new Claude reasoning skills. This spec only relocates existing skills across panes.

### Decisions to double-check
1. **Parallel-span resource usage.** N=5 spans times multiple Claude panes per span is 15+ concurrent `claude` processes. On a laptop with limited RAM / subscription rate limits this may stall. Worth running one full pipeline with `n=5` and instrumenting peak concurrent `claude` count + per-pane wall time before treating full parallel fan-out as the default.
2. **Sentinel file race.** If a pane writes `out.done` before its `out.txt` is fully flushed, the orchestrator may read partial output. Spec the protocol as: write `out.txt` first, `sync`, then `touch out.done` — and the orchestrator only reads `out.txt` after seeing the sentinel. Confirm during implementation.
3. **`clear-and-talk` inside a pane** assumes the pane is a `/crew`-style Claude session that understands the `/clear` command. If we're driving a plain `claude` invocation per send-keys round instead, the equivalent is just starting a fresh `claude` process — cheaper but loses any cached transcript reads. Pick one consistently before implementation.
4. **mcptube `add` cost.** `mcptube add <url>` may itself download / transcribe / index the video, which overlaps with `src-prep`. If mcptube's internal work duplicates whisper's, we're paying for the same transcription twice. Worth verifying mcptube's `add` cost on a real URL before locking in.

---

## 2. broll accuracy pass

### Working definition
A targeted upgrade to the existing `broll` skill (`.claude/skills/broll/`) that makes the Pexels clips in the bottom blurred bar match what the speaker is saying — both *what* appears and *when* it enters/exits, AND a structural split of the skill into picking and compositing so picking can run in parallel with captions/title (see section 1). Two output-quality failure modes are being fixed: (1) vague or off-topic clips chosen because Pexels' top result was weak, and (2) clip durations that don't line up with the spoken phrase. Not a rewrite of anchor detection, overlay region, or the choice of Pexels as the source.

### Who uses it and how
Invoked by the phase-3 broll pane (per section 1) as `broll-pick <input> <transcript.json> <broll_plan.json> [ingest.json] [chunks.json]`, then by the phase-4 completion pane as `broll-composite <input> <broll_plan.json> <out>`. `shorts.sh` is updated to call both in sequence so non-interactive mode keeps working. No new user-facing flags except an optional vision-call budget override.

### Skill split
- **`broll-pick`** — Claude-driven. Detects anchors, generates queries, fetches Pexels candidates, runs the batch vision check, optionally rewrites queries, downloads the chosen clips into `work/<id>/broll_NN/`. Emits `broll_plan.json`: a list of `{t0, t1, query, clip_path, anchor_word}` entries. No video output. This is the slow, parallelizable phase.
- **`broll-composite`** — pure ffmpeg. Reads `broll_plan.json` and the finished (loudnorm) clip, overlays each entry into the bottom blurred bar with the existing position/size. Emits the final brolled clip. This is the fast, sequential phase that must run after captions+title+loudnorm.
- Idempotency keys split: `broll-pick`'s cache keys off input clip + transcript + chunks mtimes; `broll-composite`'s keys off input clip + `broll_plan.json` mtime.

### Core features
- **Duration snaps to caption chunks.** Each b-roll slot's `[t0, t1]` aligns to the boundaries of the `chunk-captions` output for the same clip. A slot spans one or more whole chunks — never enters or exits mid-word.
- **Candidate pool from Pexels, not top hit.** `fetch_pexels.py` returns the top 3 video results per query (still smallest landscape ≥ requested duration), not just #1.
- **Batch vision check.** Per query, Claude is sent one combined image: a 3-frame strip (start/mid/end) for each of the 3 candidates. Claude returns either the index of the best-fitting candidate, or "none pass."
- **Query-rewrite fallback.** If no candidate passes the first batch check, Claude rewrites the query (text-only call) with a different angle — literal → metaphorical, or abstract → embodied. A second Pexels pull + second batch check runs against the rewritten query.
- **Drop on double miss.** If the rewritten batch also returns "none pass," the anchor is dropped — bottom bar shows the blurred background during that span. Gaps are already an accepted state in the current skill.
- **Hard per-clip cap of vision calls** (configurable via `BROLL_VISION_CAP`, default 10). Tracked in `broll.sh` across the clip's anchors. Once hit, remaining anchors take Pexels' top result without verification (current behavior). Default sized for ~5 anchors × 2 calls each (original batch + rewritten batch).

### Rules and edge cases
- **No chunk-captions output available** (skill run standalone or on an older clip): fall back to the existing 2–5s clamp. Logged to stderr.
- **Anchor's natural span crosses many chunks**: clamp to a max of 5s of chunk coverage so a single slot can't dominate. If 5s isn't a chunk boundary, end on the last chunk fully inside 5s.
- **Anchor's chunk is < 2s**: extend forward to include the next chunk; if still < 2s, drop the slot (matches existing min-2s rule).
- **Cap exhausted mid-clip**: log which anchor first ran un-verified, so debugging can spot regressions.
- **Pexels returns < 3 results** for a query: batch-check whatever came back (1 or 2). Pass criterion unchanged.
- **Idempotency unchanged**: `<out>.brollmeta` still keys off input + transcript mtimes. Adding `chunk-captions` output mtime to the key so a re-chunked clip invalidates the cache.

### Look and feel
Overlay region unchanged: bottom blurred bar at `y=1332`, size 1080×520, 16:9 letterboxed. No new transitions or color treatments. The improvement is invisible when working — only noticeable when watching back-to-back with current output and seeing the clip now actually shows the thing.

### Resolved decisions

#### Where to fix the "vague clip" problem
Choice: Verify-and-retry loop with vision check on downloaded candidates.
Why: The user picked this over query-only tightening, candidate-pool scoring without vision, or multi-query diversity. The reasoning was that even with a good query, Pexels' top hit is sometimes a dud; only inspecting the actual asset catches that. The other options either trust Pexels too much (better queries) or don't verify the asset (multi-query).

#### What the vision check sees
Choice: 3-frame strip per candidate (start / midpoint / end).
Why: Pexels thumbnails are marketing frames and can hide bad motion or off-topic middles. A 3-frame strip costs ~3× the tokens of a single frame but catches clips where the relevant action only happens late. The user picked this over thumbnail-only and over a two-stage thumbnail-then-strip gate.

#### How Claude picks among candidates
Choice: Rank-within-batch — all candidates' frame strips in one Claude call, Claude returns best index or "none."
Why: The user picked this over per-candidate pass/fail and per-candidate 0–10 scoring. It cuts vision calls by ~3× per query (one batch call vs. one-per-candidate) and gives Claude a comparative signal, which is more reliable than absolute thresholds against an unseen calibration.

#### Fallback ladder when the batch returns "none"
Choice: Rewrite the query once (text-only Claude call), pull top 3 again, batch-check again. If still "none," drop the slot.
Why: The user picked "cycle results, then rewrite, then drop" from a ladder of options. Batch ranking already handles the "cycle results" step inside one vision call, so the effective ladder becomes: original batch → query rewrite + new batch → drop. Same intent, fewer calls.

#### What duration source to use
Choice: Snap to `chunk-captions` output boundaries.
Why: The user picked this over sentence boundaries, audio-pause detection, and a per-anchor phrase heuristic. The artifact already exists in the pipeline per clip, so it's free; chunks are sized to the spoken phrase by design, so b-roll riding on chunk boundaries is automatically beat-aligned.

#### Anchor detection scope
Anchor detection (NOUN/VERB/EMOTION/PIVOT tagging in `build_prompt.py`) was *not* excluded — left in scope but no specific change requested; treat as adjustable only if it's the cheapest way to make the rest of the spec work.

### Technical constraints
- Stack unchanged. Claude via host session (`claude -p`); ffmpeg for frame extraction and overlay; Python for orchestration and the Pexels HTTP call.
- No new dependencies. Frame extraction uses the existing ffmpeg; vision calls ride the same `claude -p` path as today's text calls.
- `PEXELS_API_KEY` still required, still loaded from `.env`. Missing key → skip skill (existing behavior).
- Idempotency cache key extended to include `chunk-captions` output mtime.
- stderr logging for: cap exhaustion (which anchor), per-anchor outcome (kept / dropped / unverified-top-hit), batch-check raw response. No new files written beyond the existing `.brollmeta`.

### Out of scope
- Moving the b-roll overlay region or resizing it.
- Adding a non-Pexels video source (Pixabay, Storyblocks, generated, local library).
- Changing anchor detection in `build_prompt.py` (NOUN/VERB/EMOTION/PIVOT tagging).
- Picture-in-picture, full-bleed, or top-bar b-roll variants.
- Any change to subtitles, title card, CTA, or bg-music.

### Decisions to double-check
1. Chunk-captions boundaries as the duration source. If chunk-captions ever produces very long chunks (e.g. a single 6s phrase), the 5s clamp will cut mid-chunk again — partially defeating the snap rule. Worth eyeballing chunk-captions output on a real clip before locking this in.
2. Cap = 10 with rank-within-batch. This was sized for ~5 anchors × 2 calls each. If real shorts have more anchors than that (the current skill can produce 6–8 on a busy 60s clip), the cap will burn out and the tail of the clip will silently fall back to un-verified top hits. Worth instrumenting the first run and raising the default if the cap exhausts on typical inputs.

---

## 3. Within-short editing pass

### Working definition
A second layer of editing intelligence applied *inside* each picked short, so the finished clip reads as an edited piece rather than a raw extract of the source. The first layer (`segment-topics` → `pick-segments` → `verify-coherence`) decides *which* spans become shorts; this layer decides *how the short itself is cut*. Three failure modes are being fixed: (1) shorts that start or end mid-sentence / mid-thought, (2) shorts that drag because filler words, trail-offs, false starts, and digressive asides survive, and (3) shorts with dead air between phrases that flattens pacing. Existing skills (`bookend-trim`, `trim-filler` + `cut-filler`, `tighten-pace`) already cover each axis but in practice the output still feels chunky — this section tightens them and adds a verification gate.

### Who uses it and how
Runs inside the phase-2 editor pane (per section 1), per span, against the post-`cut-clip` + `rebase` clip. No new user-facing entry point; this is a quality pass on existing skills. The editor pane already runs `bookend-trim` → `cut-clip` → `rebase` → `trim-filler` → `cut-filler` → `tighten-pace` → `fit-vertical`. This section adds one new skill (`verify-bookends`) at the end of editing and makes `trim-filler` substantially more aggressive.

### The three axes

**Axis A — Clean start and end (bookend integrity).**
`bookend-trim` runs before `cut-clip` against the source transcript. It can pick a sentence boundary that exists in the transcript but turns out to coincide with a breath cutoff, a partial word, or a co-speaker interjection that whisper mis-bounded. Add a post-edit verifier:
- **New skill `verify-bookends`** runs at the very end of the editor pane (after `tighten-pace`, before `fit-vertical`). Claude is shown the first ~1.5s and last ~1.5s of the clip's *trimmed* transcript (post `cut-filler` + `tighten-pace` shifts) plus a 3-frame strip from each end. It returns either "clean" or proposed inward-only `t0`/`t1` adjustments (snap to the next/previous word boundary inside the clip). Adjustments apply via a second `cut-clip` re-trim and `rebase` against the trimmed transcript. Outward adjustments are NOT allowed — `bookend-trim`'s outward extension already had its chance.
- Drop rule: if either bookend cannot be cleaned without removing more than 2s, the span is marked failed and skipped at the phase 2/3 boundary (matches section 1's per-span failure rule).

**Axis B — Aggressive filler / trail-off / aside removal.**
`trim-filler` today removes umms, false starts, and obvious dead phrases, but conservatively. Tighten:
- **Lower the conservativeness bar.** Claude's prompt is updated to remove any inter-sentence digressive aside that doesn't reinforce the short's dominant topic (handed in from `verify-coherence`'s tightened span). Standard filler list (um, uh, like, you know, sort of, kind of, I mean, basically) is treated as always-removable rather than judgment-call.
- **Repeated re-starts collapse to the final take.** If the speaker restarts the same sentence 2+ times, keep only the last attempt. This is a new explicit rule in the prompt; today it's left to Claude's judgment and frequently the first take survives.
- **Hard ceiling on kept duration.** `trim-filler` may not increase a span's duration; if Claude's keeps total *more* than the input duration (a parsing/merge bug we've seen once), fall back to no-op and log.

**Axis C — Dead air between phrases.**
`tighten-pace` already collapses inter-word gaps > 0.25s. Confirm it runs *after* `cut-filler` (so it sees the trimmed timeline, not the raw one — re-timed transcript must be the input), and tighten the default:
- Drop default gap threshold from 0.25s to 0.18s. Anything above 0.18s of inter-word silence collapses to 0.08s. This is the single highest-leverage change for "feels chopped, not extracted."
- Preserve gaps that overlap a sentence boundary in the transcript at 0.15s (not 0.08s) so the listener still hears a beat between thoughts. New parameter `sentence_beat=0.15`.

### Order inside the editor pane
1. `bookend-trim` (Claude, against source transcript) — picks initial sentence-bounded `[t0, t1]`.
2. `cut-clip` + `rebase` (bash) — produces clip-local transcript.
3. `trim-filler` (Claude, post `clear-and-talk`) → `cut-filler` (bash) — aggressive pass per axis B; emits trimmed video + trimmed transcript.
4. `tighten-pace` (bash) — gap collapse per axis C against the trimmed transcript; re-emits video + re-timed transcript.
5. `verify-bookends` (Claude, post `clear-and-talk`) — final bookend check per axis A against the post-tighten clip; may issue one inward `cut-clip` + `rebase`.
6. `fit-vertical` (bash).

Three Claude reasoning jobs in the editor pane now (`bookend-trim`, `trim-filler`, `verify-bookends`), each separated by `clear-and-talk` so context doesn't bleed.

### Core features
- **No new user-facing flags.** Defaults change; legacy values overridable via env (`TIGHTEN_GAP`, `TIGHTEN_SENTENCE_BEAT`, `VERIFY_BOOKENDS=0` to disable).
- **Skill atomicity preserved.** `verify-bookends` is a single Claude reasoning step that emits either `{"action":"keep"}` or `{"action":"trim","t0":..,"t1":..}`. Cutting is delegated to a second `cut-clip` invocation — `verify-bookends` itself never touches video.
- **Re-timed transcript is the source of truth from step 3 onward.** `tighten-pace` and `verify-bookends` both read the trimmed/re-timed transcript, not the original. Downstream skills (`chunk-captions`, `burn-subtitles`, `generate-title`) already consume the final re-timed transcript per existing contract.

### Rules and edge cases
- **`verify-bookends` proposes a trim that would make the short < 15s:** reject the trim, keep current bookends, log. Don't let bookend cleanup turn a 22s short into a 12s stub.
- **`trim-filler` removes > 40% of the span:** suspicious — log a warning but keep the trim. This usually means the source span was mostly filler, which means `pick-segments` mis-ranked it; the warning is the signal to investigate, not block the run.
- **`tighten-pace` finds no gaps > threshold:** no-op, emit input unchanged. Already the existing behavior, called out so the new lower threshold doesn't accidentally force re-encoding when nothing changes.
- **Sentence boundary detection for `sentence_beat`:** use the trimmed transcript's sentence-final punctuation (`.`, `?`, `!`) on the word *before* a gap. If trimmed transcript has no punctuation (whisper sometimes drops it), all gaps collapse to the short value — acceptable, since the punctuation absence already implies less natural sentence structure.
- **Idempotency:** each skill keys off its inputs as today. The new `verify-bookends` keys off (clip, trimmed-transcript) mtimes. Re-running the editor pane on an unchanged clip is a no-op end-to-end.

### Look and feel
Finished short: clean opening word, clean closing word, no umms, no "uh wait let me start that again," gap between phrases tight enough that the next sentence lands before the viewer's attention drifts but with a perceptible beat between thoughts. Goal cadence: feels like a TikTok edit, not a Zoom recording trimmed at the ends.

### Resolved decisions

#### Where to put the bookend verifier
Choice: Post-edit verification (`verify-bookends`) as a separate skill, after `tighten-pace`.
Why: `bookend-trim` runs against the source transcript and can't see how the edit will sound after filler+gap removal. A post-edit check sees the actual final audio shape. Kept as a separate skill (not folded into `bookend-trim`) because the input contracts are fundamentally different — `bookend-trim` reads source transcript ± context, `verify-bookends` reads clip-local trimmed transcript + frame strips.

#### How aggressive `trim-filler` should be
Choice: Treat standard filler list as always-removable; collapse repeated re-starts to last take; let Claude remove off-topic asides based on the `verify-coherence` topic.
Why: Today's conservative default leaves shorts feeling unedited. The risk of over-trimming is bounded by `verify-bookends` catching abrupt cuts and by the 40% warning. The risk of under-trimming has been the actual observed regression.

#### Default `tighten-pace` threshold
Choice: 0.18s with a 0.15s sentence beat.
Why: 0.25s preserves natural breath pauses but leaves the clip feeling slack. 0.18s is below typical breath length so breaths get collapsed except at sentence boundaries, which is the desired feel. Numbers are guesses informed by listening — worth A/B'ing on a real clip during implementation (see double-check #1).

#### Outward-only vs. inward-only re-trim
Choice: `verify-bookends` inward only.
Why: Outward needs source-transcript access and `bookend-trim` already did that pass. Letting the verifier reach outward also risks reintroducing the very bookend problem it's trying to fix. Inward is safe and idempotent.

### Technical constraints
- No new external dependencies. Frame extraction for `verify-bookends` uses existing ffmpeg.
- One additional Claude reasoning call per span (vision-enabled, ~2 frames per end = 4 frames total). Adds modestly to the per-span cost; bounded by the same subscription path as today's Claude-driven skills.
- `tighten-pace` parameter names: `gap` (default 0.18), `sentence_beat` (default 0.15), `collapse_to` (default 0.08). Existing `0.25` callers either pass through env or accept the new default.
- `verify-bookends` lives at `.claude/skills/verify-bookends/` with the standard SKILL.md contract.
- Re-timed transcript file naming unchanged (`transcript.trimmed.json`); `tighten-pace` continues to overwrite it in place after gap collapse.

### Out of scope
- Mid-clip jump-cut insertion beyond filler/aside removal (e.g. cutting on a beat for stylistic punch). The pipeline cuts on *what was said*, not on rhythm.
- Re-ordering content within a short. Speaker-original order is preserved.
- Multi-speaker turn-trim logic (cutting an interlocutor's interjection). Current source material is single-speaker dominated; revisit if multi-speaker shorts become a target.
- Replacing `bookend-trim` with a single combined start/end skill — keeping the two-pass design (outward at `bookend-trim`, inward at `verify-bookends`) is intentional.
- Any change to `chunk-captions`, `burn-subtitles`, `generate-title`, `title-transition`, `broll`, `like-subscribe-overlay`, `loudnorm`, or `bg-music`.

### Decisions to double-check
1. **Tighten-pace threshold of 0.18s.** Picked by ear, not measured. Worth running one short with 0.25 / 0.20 / 0.18 / 0.15 side-by-side and locking in the value that doesn't introduce audible clipping on plosives. The `collapse_to=0.08` floor is similarly a guess — if it sounds like words butt directly into each other, raise to 0.10.
2. **`verify-bookends` token cost.** Four extracted frames + ~1.5s of transcript at each end is a small call, but it runs per span. On a 5-span run that's 5 extra vision calls. Cheap, but worth measuring against the section 1 / section 2 vision budget so total Claude usage per `/start` stays in a sane range.
3. **Interaction with `chunk-captions`.** Once `verify-bookends` issues an inward trim, the trimmed transcript shifts again. Confirm `chunk-captions` (which runs in phase 3) consumes the *final* post-`verify-bookends` transcript, not a stale one. Trivial path bug to make, worth a smoke test on first integrated run.
4. **Over-aggressive filler removal on conversational shorts.** If the source is two people in dialogue, treating "you know" / "I mean" as always-removable can strip conversational glue and make a back-and-forth feel robotic. Single-speaker monologue is the current default target, so this is acceptable now — flag for revisit if multi-speaker becomes common.
