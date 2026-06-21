# SPEC — Selection / Repair / Drip Suite (3 new skills + 2 modifications)

_Definitive plan from the 2026-06-20 analytics review. Grounded in: 28-day channel data (n=19 uploaded / 101 produced), the channel audience-retention curve, a vision audit of uploaded winners vs a never-uploaded backlog sample, and external short-form research. Authored after a 3-angle design panel + adversarial feasibility critique._

## The problem this fixes

**101 shorts produced, 19 uploaded (19%). The 82 unposted clips are not dross.** A sampled cold-open audit of never-uploaded clips across 6 sources returned **3 GOLD (upload-ready) + 5 FIXABLE (one auto-repairable defect) + 0 DROSS**. So the gap between "made the cut" and "didn't" is **not intrinsic clip quality — it's the total absence of a selection / repair / scheduling mechanism**, plus one recurring defect (`fill-vertical` framing shot 0 as a loose saliency/listener crop → the speaker's face is withheld past the 2s swipe gate).

The pipeline today is **open-loop and produce-only**: it renders clips and stops. No skill ever inspects a *delivered pixel-level artifact* for upload-readiness (`qc-clip` is duration/size only; `visual-cadence` is one diagnostic). The human picks ~19 by hand and dies 37% of the time on topic, while ~80 quality clips rot and the channel takes 7-day dark gaps.

## The two leaks the data proves (both unconfounded)

1. **Front swipe-gate** — YouTube's trial phase caps a Short at ~10k views if too many swipe in the first 2-3s. The channel sits at **56.8% "stayed to watch" / 58.6% avg-% viewed** — both below benchmark. The recurring cause is the cold-open b-roll burying the face.
2. **Throughput / cadence** — 82 unposted clips, 53 from one source, and a self-inflicted 7-day zero-view gap. No tail (86-100% of views in days 1-3), so a dark day is permanent lost reach.

## Benchmarks the suite targets (external research)

| Metric | Channel now | "Cold / dead" | "Fire" target | Source |
|---|---|---|---|---|
| Stayed-to-watch (VVSA) | **56.8%** | >52% swipe-away | ≥70% viewed (swipe-away <30%) | Paddy Galloway 3.3B-shorts study; Think Media |
| Avg % viewed (APV) | **58.6%** | ~52% | ≥80%; viral 95-98% | Think Media / YouTube |
| Retention to blow up | — | <90% | 90% min, 95%+ via loops/rewatch | Jenny Hoyos |
| Delivered duration | ~25-44s | ≤30s (worst bucket) | **45-59s** when APV holds | Paddy Galloway / Marcus Jones |
| Time-to-full-hook | — | mid-sentence/no context | premise+implied payoff **<5s**, decision in 1-3s | Logan E. Smith; heyDominik |
| Dead tail cost | — | — | end RIGHT after payoff (1 dead sec ≈ 3% retention) | Hoyos |

**Notable calibration flag:** research says 45-59s clips win when retention holds, and our own data agrees (40-44s Huberman clips out-retained the 25-30s ones). Our aggressive trim + the 1.25x `speed-up` are pushing delivered runtime toward the ≤30s **worst** bucket. See Appendix D.

---

## THE DEFINITIVE SET

### NEW SKILL 1 — `grade-clip` (the keystone — build first)
Per-clip **upload-readiness grade (0-99)** read off the *finished* `.mp4` + its persisted sidecar plans. The first skill in the pipeline that inspects a delivered pixel-level artifact, and the on-disk translation of the un-exportable VVSA gate.

- **Chain position:** runs at the end of the per-span chain (after `save-local`) AND is invocable standalone over the whole `output/` backlog.
- **Inputs:** the rendered `.mp4`, plus existing sidecars — `.fillplan.json` (per-shot `kind`/crop), `.chunks.json` (caption timing), `.cadence.json` (longest static gap), `broll_plan.json`, `.title.txt`, `transcript`.
- **Output:** `clip_NN.grade.json` → `{grade:0-99, tier:GOLD|FIXABLE|DROSS, hard_caps:[...], signals:{...}, fix_routes:[...]}`.
- **Algorithm — deterministic retention-proxy floor (no model):**
  - `frame1_is_face` — MediaPipe on frame 0 **and** `.fillplan.json` shot0 `kind != 'face'` (free read; this is the literal mechanical cause of the audit's "face withheld" defect).
  - `letterbox_bars` — detect blur-bar/pillarbox regression (pixel variance on edge columns).
  - `credit_lit_at_open` — is the source-credit band rendered in [0, ~1s] instead of only the final `CREDIT_TAIL`?
  - `first_visual_change_by_3s` — does any jump-cut/zoom/b-roll/caption-swap land before 3.0s (read the plans, no decode)?
  - `first_payoff_offset` — chunks.json vs the title's key noun: how many seconds until the turn lands (target <3s; the 0:08-0:13 step leak).
  - `longest_static_gap` — read `.cadence.json`.
  - `opening_caption_words` — is there a legible muted-viewer text hook in the swipe window?
  - `max_residual_silence` — `ffmpeg silencedetect` (dead-air > threshold).
  - `terminal_loop_score` — frame-1 vs last-frame similarity (the >100%-retention loop lever; Appendix B).
  - **Any hard regression (letterbox / blocking card / face-withheld / credit-at-open / dead tail) caps `grade ≤ 40`.**
- **Algorithm — one batched Claude pane call (the only model use):** hook↔payoff coherence + open-loop strength + cold-viewer-context, rated 0-10, on the opening transcript + title. `GRADE_SKIP_CLAUDE=1` → proxy-only fast sweep for a first backlog pass.
- **Knobs:** `GRADE_MIN_UPLOAD` (default 60), `GRADE_SKIP_CLAUDE`, the proxy thresholds.
- **Why new:** nothing inspects a delivered artifact for upload-readiness; `qc-clip` is duration/size only.
- **First-class output:** a backlog **triage report** (`output/_triage.json`) — gold/fixable/dross counts + which defect per clip. This is the single artifact that turns 101-produced/19-uploaded into "ship these 30 now, fix these 50, skip these."

### NEW SKILL 2 — `fix-cold-open` (recovers the ~5/8 fixable backlog)
Deduction-targeted **deterministic repair of a finished short**, driven by `grade.json`. Fixes the recurring defect without a 30-step re-pipe.

- **Chain position:** in-chain on `.brolled.mp4` (preventive) AND standalone over any flagged backlog clip (curative).
- **Inputs:** the `.mp4` + its `grade.json` + `.fillplan.json` + `broll_plan.json`.
- **Output:** a repaired `.mp4` + `.fixmeta` signature; or `rerun_recommended` when the defect is structural (letterbox = old render).
- **Algorithm — three gated ops:**
  - (a) truncate any `broll_plan` "picks" window overlapping [0, ~2.2s] and re-composite so frame 1 is the speaker, not a cutaway.
  - (b) when `.fillplan.json` shot0 `kind != 'face'`, force a `fill-vertical` speaker re-punch on shot 0 (re-runs detection — identity clusters aren't persisted; **flag this cost**).
  - (c) re-fire `brand-overlays`/`title-transition` for the credit-at-open / centered-card defects.
- **Knobs:** `FIXCO_OPEN_GUARD_SEC` (default 2.2), `FIXCO_MODE=preventive|curative`.
- **Why new:** the single highest-ROI move on the backlog — converts ~50 fixable clips to uploadable with one deterministic pass.

### NEW SKILL 3 — `schedule-drip` (kills the dark gaps + per-source fatigue)
Deterministic greedy scheduler over the graded clips. **Staging-handoff only — no auto-upload** (no API key in the stack).

- **Chain position:** end-of-run / standalone over `output/`.
- **Inputs:** every `grade.json` + `upload-log.json` (what's already posted) + a checked-in topic scorelist (Appendix C).
- **Output:** dated staging folders `output/_toupload/<date>/` each with the clip + `metadata.txt` (lowercased title + winning-topic hashtags) + `gap_warnings`.
- **Algorithm:** rank by grade, gate by topic scorelist, **de-dupe near-identical clips**, enforce `MAX_PER_SOURCE_PER_DAY=1` round-robin (the 53-from-one-source feed-fatigue fix), fill `POSTS_PER_DAY` (default 1-2) from the top, drop anything in `upload-log.json`, and **emit a warning before any day with no scheduled post**.
- **Knobs:** `POSTS_PER_DAY`, `MAX_PER_SOURCE_PER_DAY`, `DRIP_HORIZON_DAYS`.
- **Why new:** there is no selection/scheduling step at all; this is the only skill that directly attacks the #1 unconfounded leak (the dark gap) and the backlog rot.

### MODIFY 1 — `pick-segments` (stop producing the rejects)
Formalize `overall_score` as an explicit 0-99 rank with **(a) a hook↔payoff coherence term and (b) a time-to-first-payoff term** (penalize spans whose turn lands >3s into the delivered window). Have `start.sh` take the top `SHORTS_N` **by score**, not first-N-found. Bias `t0` toward opening on/near the turn line; up-weight open-loop `hook_type`s. The cheapest upstream win — fewer setup-heavy bait-openers reach `grade-clip` at all.

### MODIFY 2 — `verify-bookends` (cold-viewer context gate)
Add a deterministic-plus-Claude gate: classify whether the **first delivered sentence stands alone for a stranger** (dependent clause / pronoun-without-referent / fragment fails) and snap `t0` FORWARD to the next context-bearing sentence within the 3s payoff budget. Tighten the existing "first 3s pure setup" trigger to a hard time-to-first-payoff budget. Emit `context_pass` + `first_payoff_offset` for `grade-clip` to consume (no double work, no new model).

---

## Build order & dependencies
1. **`grade-clip`** (deterministic floor first, ship, then add the Claude rubric) — everything consumes its `grade.json`.
2. **`fix-cold-open`** — routed by `grade.json`; immediately recover the backlog.
3. **`schedule-drip`** — needs grades + the topic scorelist.
4. **`pick-segments` / `verify-bookends` mods** — cheap upstream wins; reduce what the grader rejects.

## Immediate payoff (no new uploads required)
Run `grade-clip --backlog` over `output/`, then `fix-cold-open` on the FIXABLE set, then `schedule-drip`: the sampled rate (3/8 gold, 5/8 fixable) projects to **~30 ship-now + ~50 one-pass-fixable clips** staged into a multi-week daily drip — from a standing start, with zero new source ingestion.

---

## Appendix — strong ideas surfaced but deferred (not in the core 5)
- **A. Static topic allow/deny scorelist (do this with `schedule-drip`).** n=19 across collinear topics is too small to *learn* a topic prior, but the deaths cluster by topic *now*. Ship a checked-in `topics.scorelist` (science/self-improvement + celebrity-story = GO; generic-productivity / unknown-TEDx-software / #aivideo = HOLD). A future ledger only re-weights it.
- **B. `seamless-loop` finisher (the >100%-retention lever nobody built).** Match the last ~150ms frame/audio energy to frame 1, or prefer payoffs whose closing visually rhymes with the open. Even a passive `terminal_loop_score` fed into `grade-clip` (already included) is a cheap start.
- **C. `seed-provenance` stamp (one-line enabling change).** `scout-sources` writes no seed→source back-reference, so no source-side learning loop can ever fire. Stamp the winning seed query into `candidates.json` → carry into `ingest.json`. Cheap; unblocks all future niche feedback.
- **D. Duration / `speed-up` calibration.** Measure delivered runtime against the 45-59s sweet spot; consider relaxing the trim/`SPEED` defaults so finished clips land at 40-55s instead of ≤30s when APV is high. Could replace a modification if preferred.
- **E. `hook-text-burn` (next build after the spine).** Burn a legible muted-viewer text hook (the premise/open-loop) in the swipe window; load-bearing constraint is a `HOOK_Y_FRAC` overlap check against the caption band to avoid the double-caption regression the audit caught.

## Caveats
- The closed-loop / learned-niche ideas were **demoted**: at n=19 across collinear topics, with no seed-provenance join on disk, they manufacture priors from noise. The plan uses a **static scorelist now**, ledger-learning later.
- `fix-cold-open`'s shot-0 re-punch must re-run face detection (identity clusters aren't persisted) — a real per-clip cost.
- `grade-clip`'s proxies are an *approximation* of VVSA, not VVSA itself. Validate by exporting per-video swipe-away (Studio → Reach → "Viewed vs Swiped away") once a batch is posted and correlating to the grade.
