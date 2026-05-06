# Plan — Milestone 1

Waves are dependency tiers, not time estimates. Wave 1 = parallelizable
from cold start. Each task is filed as a bead pointing back to its T-NN
id. `surface` is the rough file region the task touches — used by athena
to enforce the one-bead-in-flight-per-surface rule (see CONTEXT.md
"Coordination tradeoff").

<task id="T-01" wave="1" deps="" surface="meta">
  <title>Forge proposes crew lineup for M1</title>
  <body>
  Forge reads CONTEXT.md and PLAN.md and proposes the crew lineup for
  M1 — including the two confirmed lanes (engaging-span judge for D-04,
  hook-overlay writer for D-05) plus whatever execution lanes the rest
  of M1 needs (scorer port, subtitler, grader, render-runner, etc.).
  Lineup spec includes per-lane: name, one-line job, owned surface
  label(s), CLAUDE.md outline. Forge dedupes against existing global
  crew before spawning.
  </body>
  <verify>Forge replies with a written lineup, one block per proposed
  lane. User approves or edits. Approved lanes get spawned via the
  crew/forge mechanism.</verify>
  <done>All M1 lanes spawned and pingable via
  `bash ~/.claude/skills/crew/crew.sh send <name> "ack"`.</done>
</task>

<task id="T-02" wave="1" deps="" surface="docs">
  <title>Strip polecat semantics from README and shorts-plan</title>
  <body>
  Per D-07 the crew commits straight to main, no worktrees. Update
  README.md (delete the "Polecat worktrees are reaped..." paragraph and
  the "Polecat checklist before `gt done`" section; keep the delivery
  path/naming/enforcement contract). Update shorts-plan.md if it
  references polecat or `gt done`. Add a short paragraph to README
  explaining the new convention: bead → in_progress → commit to main →
  brutus smoke → close.
  </body>
  <verify>`grep -in polecat\|gt\ done README.md shorts-plan.md` returns
  no behavioural references (matches inside historical research notes
  are fine). README still documents the delivery path / naming /
  enforcement clearly.</verify>
  <done>README.md and shorts-plan.md committed to main reflecting the
  no-branches workflow.</done>
</task>

<task id="T-03" wave="1" deps="" surface="ingest">
  <title>Fetch eval VOD suite via yt-dlp</title>
  <body>
  Add `scripts/fetch_sources.sh` (or Makefile `make sources`) that
  yt-dlps the three eval VODs into `source/` with deterministic names:
    - `source/vod-tyler1-jynxzi.mp4` (https://www.youtube.com/watch?v=u7OUP9b6MCM)
    - `source/vod-medium.mp4` (https://www.youtube.com/watch?v=2R5bqqVF2a4)
    - `source/vod-podcast.mp4` (https://www.youtube.com/watch?v=-_6mni6k0Zw)
  Skip download if file already exists. Pin format to mp4, h264, best
  audio-video merge. Add `source/` to `.gitignore` if not already.
  </body>
  <verify>Running the script on a clean checkout produces all three
  files; re-running is a no-op. `ffprobe` reports each as h264 mp4 with
  audio. None of the files are committed to git.</verify>
  <done>Script committed; user can run it once to populate the eval
  suite locally.</done>
</task>

<task id="T-04" wave="2" deps="T-01,T-03" surface="ranker">
  <title>Port v1 hook scorer into v2 ranking</title>
  <body>
  Use geoff's recon report (fired during intake) as the merge map. Pull
  HOOK_WORDS, hook_score, and the rank() integration from pipeline.py
  into pipeline_v2.py. Replace the v2 main's "ranking is just
  score_scenes energy×log(density)" with a composite that includes
  hook_score. Add the variety/min-gap re-ranker and the
  hook_in_first_3s, standalone_3s, duration_fit features described in
  sota-shorts.md:200-213.
  </body>
  <verify>Smoke run on `source/vod-tyler1-jynxzi.mp4` produces
  `delivered/<bead>-<ts>-short-01.mp4` whose first 3s contains an
  interjection from HOOK_WORDS. Two consecutive shorts are not from
  the same 10-minute window of the source.</verify>
  <done>pipeline_v2.py uses the composite ranker by default; legacy
  energy-only path removed. Smoke output exists in delivered/ and is
  watchable.</done>
</task>

<task id="T-05" wave="2" deps="T-01" surface="subtitles">
  <title>Word-level karaoke subtitle renderer</title>
  <body>
  Add the rendering primitive that selective subtitles will sit on top
  of. mlx-whisper large-v3 already runs per-clip; add a whisperX
  phoneme-alignment pass (per sota-shorts.md:182-190 — only the
  alignment pass, not transcription) to get word timestamps. Emit ASS
  with per-word \k tags. Render via libass burn. Style: existing v2
  Helvetica 72pt, MarginV=544. Add a CLI flag `--subs-mode={line,word}`
  defaulting to `line` for now (T-06 changes the default).
  </body>
  <verify>`pipeline_v2.py --subs-mode word` on a short clip produces
  output where individual words highlight in sync; line-level mode
  still works unchanged.</verify>
  <done>Both modes render correctly on at least one clip from each of
  the three eval VODs.</done>
</task>

<task id="T-06" wave="3" deps="T-04,T-05" surface="subtitles">
  <title>Selective subtitles — burn only on engaging spans</title>
  <body>
  The differentiator. Build the engagement-tagging step that runs over
  candidate spans:
    1. Local signals (D-04 path A): tag a span "engaging" if RMS
       z-score > 1.5 OR a HOOK_WORDS interjection appears OR a scene
       cut lands within 1s.
    2. Hand the local-tagged candidates to the engagement-judge crew
       lane (spawned in T-01) for a semantic Y/N pass over the
       transcript snippet. Lane returns per-span verdicts.
  In the renderer, emit ASS dialogue lines ONLY for words inside
  `engaging=true` spans. Outside those spans, the subtitle track is
  empty (no burn). Add `--subs-mode=selective` and make it the
  default.
  </body>
  <verify>On `source/vod-podcast.mp4` the rendered short has subtitles
  burned only across the engaging spans, with visible non-subtitled
  stretches between them. Spot-check 3 shorts: subtitled spans
  correspond to interjections, RMS peaks, or judge-flagged hot lines.
  </verify>
  <done>Selective mode is the default; non-engaging stretches render
  cleanly with no subtitle artifacts.</done>
</task>

<task id="T-07" wave="3" deps="T-04" surface="overlay">
  <title>Hook-overlay text generator (crew-lane driven)</title>
  <body>
  For each shortlisted clip, ask the hook-overlay crew lane (spawned in
  T-01) to produce one overlay-text candidate (1 line, 5-7 words,
  TikTok-grammar). Render as ASS title at the top of the frame, above
  the screen panel. Behind a flag `--overlay={off,on}`; default `on`.
  Lane gets the clip's transcript snippet + the hook_score features as
  input.
  </body>
  <verify>Three smoke renders across the eval suite each have a
  legible overlay line at the top, distinct per clip, that reads as a
  hook for the moment.</verify>
  <done>Overlay generator wired and the three smoke shorts ship with
  their overlays in delivered/.</done>
</task>

<task id="T-08" wave="3" deps="T-04" surface="eval">
  <title>Eval / QC loop with auto-rejection</title>
  <body>
  After every render, the grader crew lane (spawned in T-01) runs
  metrics:
    - Hard fails (auto-move to `delivered/rejected/<reason>/`): file
      <100KB; duration <25s or >65s; loudnorm I outside [-15,-13];
      face-tile black >50% of frames; transcript empty.
    - Soft flags (warn in verdict file, keep in `delivered/`):
      reframe jerk above threshold; hook-window energy below
      threshold; no interjection in first 3s.
  Write `delivered/<bead>-<ts>-<stem>.verdict.json` next to each
  render. The grader never deletes; rejection moves only.
  </body>
  <verify>Synthetic bad render (e.g. 10s file) is moved to
  `delivered/rejected/duration/`. Healthy render keeps a verdict.json
  alongside it in `delivered/`.</verify>
  <done>Eval runs automatically after every pipeline_v2 render; main
  `delivered/` contains only renders that passed hard checks.</done>
</task>

<task id="T-09" wave="4" deps="T-04,T-08" surface="ranker">
  <title>Multi-variant A/B emitter (trim variants)</title>
  <body>
  For each top-N shortlisted moment, emit 2 variants with the same
  core payoff but trim windows differing by ±5s lead. Both variants go
  through the eval loop independently; both land in `delivered/` if
  they pass. Naming: `<bead>-<ts>-short-NN-a.mp4` /
  `<bead>-<ts>-short-NN-b.mp4`.
  </body>
  <verify>Smoke run produces variant pairs visible in `delivered/`.
  The two variants of one moment differ only in their lead window;
  payoff alignment is preserved.</verify>
  <done>A/B emitter is the default behaviour for top-N; eval loop
  treats each variant independently.</done>
</task>

<task id="T-10" wave="4" deps="T-06,T-07,T-08,T-09" surface="meta">
  <title>End-to-end M1 acceptance run across the eval suite</title>
  <body>
  Run pipeline_v2.py end-to-end against all three eval VODs with the
  full M1 stack on (composite ranker + selective subtitles + overlay +
  A/B + eval loop). Confirm `delivered/` ends up with a meaningful set
  of variants per VOD and `delivered/rejected/` shows the loop is
  catching bad renders. Brutus signs off.
  </body>
  <verify>For each of the three VODs: at least 3 shorts in
  `delivered/`, at least 1 A/B pair, all pass eval hard checks; at
  least one rejection somewhere in `delivered/rejected/` proving the
  loop bites.</verify>
  <done>Brutus posts an M1 sign-off; user can browse `delivered/` in
  Finder and watch the artifacts.</done>
</task>
