# SPEC: Style Replication — reference-conditioned learning loop

Learn *how top shorts are edited* (Group C exemplars: finished pixels + audio only)
and steer the pipeline's CODE/knobs so *our* shorts (Group B) reproduce that craft.
The load-bearing idea: a versioned **Style Profile** is the shared intermediate
representation both C and B reduce into, so comparison happens in text/JSON space
and feedback acts on the codebase — every future span and run inherits it.

Three skills:

| skill | phase | what |
|---|---|---|
| `profile-clip` | shared organ | sidecar-free analyzer: any finished `.mp4` → `*.styleprofile.json` (pixels + audio only) |
| `style-corpus` | offline LEARN | `learn <url>…` (yt-dlp → profile-clip → `references/profiles/`), `distill` (→ `references/targets.json`), `show` |
| `style-gate` | online PRODUCE+VERIFY | span-0 pre-fanout match gate: profile span 0 from pixels, diff vs targets, move knobs, re-render, re-match, then fan out |

## 1. Style Profile schema (v1)

`style_profile_version: 1`. Grounded in the actual Group C material (the MrBeast
sprite sheets): dense archival/b-roll cutaways (~40-60% of frames off the talking
head), 1–2s shot rhythm, constant 1-line ALL-CAPS captions with one accent word,
top-banner title in the open, near-zero dead air.

**The lever rule:** every field is either mapped to a reachable code lever
(`lever` in `style-gate/match.py::LEVERS`) or explicitly **diagnostic-only** —
diagnostic fields can NEVER fail the match gate. This is the unreachable-target
protection: production facts (multicam, staged sets, cast size) are measured and
reported but can't thrash the codebase.

```json
{
  "style_profile_version": 1,
  "clip": "…", "duration_sec": 41.2,
  "cuts":     { "cuts_per_min": 34.9, "median_shot_sec": 1.4, "p90_shot_sec": 3.8,
                "longest_static_gap": 4.1 },
  "speech":   { "words_per_min": 188, "max_silence_sec": 0.4, "speech_fraction": 0.93 },
  "visual":   { "face_fraction": 0.55, "cutaway_fraction": 0.45, "cutaway_count": 9,
                "opens_on_face": true },
  "captions": { "present_fraction": 0.9, "band": "lower_third" },
  "audio":    { "onsets_per_min": 11.0, "music_floor_db": -46.5, "music_present": true },
  "hook":     { "first_cut_sec": 1.2, "title_overlay_open": true },
  "vision":   { "broll_mode": "archival", "caption_style": "karaoke_accent",
                "production_class": "single_interview", "hook_device": "claim",
                "confidence": 0.8 },
  "meta":     { "tier": {"cuts": "det", "vision": "claude"}, "needs_vision": [], "notes": [] }
}
```

Lever map (field → knob, direction):
- `cuts.cuts_per_min` / `median_shot_sec` / `longest_static_gap` → `JUMP_CUT_SEG`, `JUMP_CUT_MAX_GAP` (lower = more churn)
- `speech.words_per_min` / `max_silence_sec` / `speech_fraction` → `SPEED`, tighten-pace budget
- `visual.cutaway_fraction` / `cutaway_count` → b-roll density (`BROLL_VISION_CAP`), `SWITCH_FACES`/`SWITCH_SPACING`
- `hook.first_cut_sec` → `JUMP_CUT` lead / fix-cold-open guard (diagnostic in v1 gate)
- `audio.onsets_per_min` → `SFX_COMEDY`/`BROLL_SFX`/`TITLE_SFX` (diagnostic in v1 — audio-event detection is a coarse proxy)
- `duration_sec` → `SHORTS_DMIN`/`SHORTS_DMAX` (distill-report only; never moved per-run)
- everything under `vision.*`, `captions.band`, `audio.music_*` → **diagnostic-only**

## 2. Sidecar-free analyzer (`profile-clip`)

One skill both loops call; reads ONLY pixels + audio, never our plans — so B is
profiled exactly as C is (fairness: "C as delivered" vs "B as delivered", never
"B as intended"). Deterministic tier (all ffmpeg/OpenCV/MediaPipe, reusing
grade-clip's primitives):

- **cut rhythm**: ffmpeg scene-detect (`select='gt(scene,thr)'`) → shot list →
  cuts/min, median/p90 shot length, longest static gap.
- **speech**: local whisper.cpp (via the transcribe skill's binary from `.env`)
  when available → words/min, speech fraction; `silencedetect` → max silence.
  Whisper missing → fields null, gate skips them.
- **visual**: MediaPipe FaceLandmarker (grade-clip's model) on N sampled frames →
  face_fraction; contiguous no-face runs → cutaway_count/fraction; frame-0 face →
  opens_on_face.
- **captions**: Canny edge density in the lower-third band across sampled frames →
  present_fraction; top-band density at t≈0.6s → title_overlay_open.
- **audio events**: 50ms RMS windows from decoded PCM → onset spikes
  (flux > k·median) not inside speech → onsets/min (coarse; low confidence);
  quietest-5%-window RMS → music_floor_db → music_present.

## 3. Model routing (UniRoute-style)

Two tiers. The cheap deterministic tier fills every quantitative field and marks
`meta.needs_vision` for the enumerated judgment fields it cannot decide
(`broll_mode`, `caption_style`, `production_class`, `hook_device`, plus
`opens_on_face` when face detection returned no evidence). Escalation rule:
**one vision call per clip, only if `needs_vision` is non-empty and
`PROFILE_VISION=1`** — a single contact sheet (director-pass `frames.py`) through
`run_claude_step` (subscription; session model, swappable by the pane the caller
provides). Vision failure → deterministic profile ships with `vision:{}` and
`confidence:0` — non-fatal, and the gate only reads levered (deterministic)
fields anyway. This is the routing principle: represent the task by which fields
are low-confidence, send only those to the expensive model.

## 4. "Match" definition

**Distribution, not single exemplar.** `style-corpus distill` computes per-field
robust stats over ≥`SG_MIN_REFS` (default 3) profiles: median + MAD (σ≈1.4826·MAD,
floored at 10% of the median so a degenerate corpus can't demand exactness).
`style-gate/match.py` scores span 0's profile: field matches iff
`|value−median| ≤ SG_Z·σ` (default SG_Z=1.5). **Only levered fields participate**;
diagnostic fields are reported in the verdict but cannot fail it. Verdict:

```json
{ "match": false, "checked": 7, "mismatches": [
    { "field": "cuts.cuts_per_min", "ours": 18.0, "target": 34.9, "sigma": 6.2,
      "z": -2.7, "lever": "JUMP_CUT_SEG", "dir": "down" } ] }
```

## 5. The gate — risk ladder, bounds, rollback

Structurally `first-span-feedback` with a different oracle (corpus match instead
of grade≥prev) and a different sensor (the sidecar-free profile instead of
grade.json). Risk ladder, gentle first:

1. **Knob tier (autonomous, v1).** `moves.py` maps the worst mismatches (top
   `SG_MAX_MOVES`=2 by |z|) to clamped knob deltas written to
   `work/<id>/style.env` (e.g. `JUMP_CUT_SEG` scaled by target/ours, clamped to
   [1.8, 6.0]; `SPEED` clamped [1.0, 1.35]; `SWITCH_SPACING` [3, 10]). Re-render
   span 0 via the entrypoint-owned `SG_RERENDER_CMD` with style.env applied,
   re-profile, re-match. **Accept iff no checked field got worse (|z| non-
   increasing on every field) and at least one mismatch cleared or shrank**;
   also grade-guard: span 0's `grade.json` must not regress (reuses
   `check_grade.py` semantics, grade-only). Accept → style.env stays exported for
   spans 1..N and is appended to `references/accepted.jsonl` (the learning
   ledger). Reject → delete style.env, re-render on stock knobs is NOT repeated
   (the pre-gate render is kept; markers restored by the rerender contract).
   Bounded by `SG_MAX_ITERS` (default 1). Idempotent via `.sgmeta`.
2. **Code tier (operator-in-the-loop, v1 surfaces only).** Mismatches no knob can
   reach (or that persist after `SG_MAX_ITERS`) are SURFACED in the verdict file
   + a `bd` note — a human (or a supervised session) decides on durable skill
   edits. Rationale: knobs are per-run and self-reverting; durable code edits by
   an autonomous loop already exist (first-span-feedback) but that gate has a
   grade oracle sensitive to its own change; the style oracle is newer and
   coarser, so autonomy starts one rung lower. Flip later by giving style-gate an
   FSF-style fixer once the corpus/oracle has run history.

Autonomy overall: LEARN is operator-triggered (you pick the exemplars); the gate
runs unattended inside `start.sh`/`autopilot.sh` but only ever moves ephemeral
knobs.

## 6. Wiring

```
LEARN (offline, manual):
  style-corpus.sh learn <urlC1> <urlC2> …     # yt-dlp → profile-clip (vision on) → references/profiles/*.styleprofile.json
  style-corpus.sh distill                      # → references/targets.json (medians/MADs + n + lever map echo)

PRODUCE+VERIFY (in start.sh, after first-span-feedback, before fan-out):
  span 0 delivered → style-gate.sh <id> clip_00 <saved.mp4>
    profile span 0 (pixels only) → match vs targets
    match → exit 0 (fan out on stock knobs)
    mismatch → moves → style.env → SG_RERENDER_CMD → re-profile → re-match
      accept → export style.env for spans 1..N   |   reject → stock knobs
  spans 1..N fan out
```

`STYLE_GATE` defaults to **1 but hard no-ops when `references/targets.json` is
absent or has n < SG_MIN_REFS** — out of the box the pipeline is byte-identical
to today; the gate turns on by building a corpus, and `STYLE_GATE=0` force-kills
it. Non-fatal everywhere (any error → span 0 and knobs untouched, exit 0).
`shorts.sh` gets the same block after its first span. Env knobs: `STYLE_GATE`,
`SG_Z` (1.5), `SG_MAX_ITERS` (1), `SG_MAX_MOVES` (2), `SG_MIN_REFS` (3),
`PROFILE_VISION` (1), `PROFILE_FRAMES` (12), `PROFILE_SCENE` (0.3),
`SG_RERENDER_CMD` (entrypoint-owned), `STYLE_REFS` (corpus dir, default
`references/`).

`references/` is checked in (small JSON only; downloaded exemplar media goes to
`work/_style/<id>/` which is gitignored).

## Schema versioning

`style_profile_version` bumps on any field add/remove/semantic change; `distill`
refuses to mix versions; `match.py` refuses a targets/profile version mismatch
(no-op gate). Old profiles are re-derivable from the saved exemplar URLs in each
profile's `meta`.
