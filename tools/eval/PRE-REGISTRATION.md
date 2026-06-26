# Pre-Registration — Does the §9 entertainment-advice corpus improve clip SELECTION?

> **Committed before any ON-vs-OFF comparison is run.** This is the anti-p-hacking spine
> for epic `shorts-dwt`. The metric, the dataset split, and the pass/fail rule below are
> fixed *now*. The person who tuned the corpus (§9 of `research.md`) does **not** get to
> tune it against the held-out test sources. Edits to this file after the first ablation
> run must be logged in §8 with a reason — silent post-hoc changes invalidate the result.
>
> Companion to `eval-plan.md` (the design) and `research.md` §9 (the corpus under test).

---

## 0. The non-circularity acceptance criterion (binds every metric here)

The thing being modified **is an LLM judge** (Claude picking clip-worthy spans). Therefore
**no metric in this document may bottom out in "a Claude judge thought it was better."**
Every number below grounds out in one of three non-LLM truths:

1. **Real audience behavior** — views / CTR / average-view-duration from the YouTube Studio
   export (own catalog, Tier 3; in-niche, Tier 1).
2. **Real editors + real audience as labels** — spans professional clip channels cut AND
   that the public watched, weighted by public view count (Tier 2 gold set).
3. **Real humans, blind** — forced-choice A/B by people (secondary, small-n; not a headline).

If any scorer in this epic calls Claude to judge quality, the deliverable is wrong.

---

## 1. Independent variable (the only thing that changes between arms)

`ADVICE_CORPUS ∈ {OFF, ON}` injected into the picker prompt builder
(`pick-segments/build_prompt.py`, later `rlm-segment-subcall`):

- **OFF** = today's prompt, byte-for-byte (the control; current shipped behavior).
- **ON**  = OFF + the versioned `pick-segments/advice.md` block (the §9 corpus) and nothing else.

Everything else is held fixed within a comparison: same `N`, same `SHORTS_DMIN`/`SHORTS_DMAX`,
same source transcript, same RMS/heatmap/topics/hint inputs, same model, same decoding controls
(see §5). We are testing **L1 — Selection** only; **L2 — Production** (reframe/captions/pacing)
is never in the variable.

---

## 2. Primary metric (the headline; pre-committed)

**Primary metric = weighted overlap (Tier 2), advice-ON minus advice-OFF.**

> Weighted overlap, per source = Σ(public views of the gold spans the arm's N picks covered)
> ÷ Σ(public views of *all* gold spans for that source), where "covered" = temporal
> IoU ≥ `τ = 0.5` between a picked span and a gold span. It credits landing on the *big*
> winners, not merely on *any* editor-chosen clip.

Rationale for choosing it over the alternatives: recall@N treats a 50k-view clip and a
500-view clip as equal; rank-correlation needs many matched pairs per source (we have few);
mean-IoU rewards tight boundaries on already-found spans but says nothing about *which*
spans were found. Weighted overlap is the one metric that directly answers "did the advice
make the picker land on the moments the market actually rewarded?"

**Secondary metrics (reported always, never promoted to headline post-hoc):**
recall@N at `τ ∈ {0.3, 0.5}`, Spearman(picker `overall_score`, gold-span real views) over
matched spans, mean best-matched IoU. A secondary metric may *support* a story but can never
*rescue* a primary-metric failure.

`τ = 0.5` and `K = all gold spans` and the IoU definition (intersection ÷ shorter-span
duration, i.e. coverage of the gold span) are fixed here and not revisited per-run.

---

## 3. Datasets & the held-out split (fixed before any run)

### 3.1 Tier 3 (own catalog) — hypothesis-generator, NOT a gate
- Source: newest YouTube Studio *Table data.csv* export (currently
  `~/Downloads/Content 2026-05-26_2026-06-23 C0BALT_CUT/Table data.csv`, n≈26 videos).
- **This export carries no VVSA / "Stayed to Watch" column.** Outcome variables, in priority order:
  1. `avg_view_duration_sec = Watch time (hours)·3600 / Views` — the closest available
     retention proxy; and its clip-length-normalized form `avg_view_duration_sec / clip_duration`.
  2. `Views` (noisier, heavy-tailed; log1p-transformed for correlation).
  3. `CTR (%)` — a thumbnail/title signal, reported but NOT a selection outcome (confounded).
- Role: **prunes** advice claims that anti-correlate with our own audience before we spend
  Tier-2 effort. It never confirms the corpus and never gates ship. Observational, small-n,
  confounded by title/thumbnail/topic/posting-time — stated as a limit, not hidden.

### 3.2 Tier 2 (gold set) — the development + decision harness
- Eligible sources: those with an **official clips channel** whose clips carry public view counts.
- **Train/test split, committed now:** sources are partitioned by a deterministic hash of
  `source_id` (`int(sha1(source_id).hexdigest(),16) % 10`): buckets `0–6` = **DEV** (corpus may be
  iterated here), buckets `7–9` = **TEST** (held out; the headline CI is computed here only).
  The split is by *source*, never by *span*, so no episode straddles the fence. The bucket
  assignment is frozen in `tools/eval/splits.json` the first time the gold set is built.
- A source enters the gold set only after its alignment passes the spot-check gate (§3.1 of
  eval-plan: manually verify 10 alignments before trusting any score); the per-source align
  reject-rate is logged.

### 3.3 Tier 1 (production) — ratification, not iteration
- Autopilot tags each produced clip with its arm; VVSA/retention read back via the
  `analytics-feedback` CSV join. Powered for *non-contradiction*, not for primary inference
  (channel is low-volume; views are heavy-tailed; a realistic effect needs ~dozens/arm → weeks).

---

## 4. k repeats & sampling noise

The picker is stochastic. Each arm is run **k = 5** times per source (independent samples).
Per-source per-arm metric = the **mean over the k runs**; per-source variability across the k
runs is reported (so we can see when a "win" is within sampling noise of a single source).
Bootstrap CIs (§6) resample over **sources**, using each source's k-averaged metric.

If decoding can be pinned to deterministic (temperature 0 / fixed seed) on the dispatch path,
k may be reduced to 1 and this is logged in §8 — but the default assumption is stochastic
dispatch (the tmux-pane path does not expose a seed), so **k = 5 stands unless overridden in writing.**

---

## 5. Decoding / fairness controls

- Same model family + version for both arms (no model swap mid-experiment).
- Same `N`, `SHORTS_DMIN`, `SHORTS_DMAX`, and same upstream artifacts
  (`transcript.json`, `topics.json`, `candidates.hint.json`, RMS, heatmap) for both arms —
  ON and OFF differ **only** by the injected `advice.md` block.
- Temperature/seed pinned where the dispatch path allows; otherwise k=5 averages it out.
- The OFF arm must reproduce today's shipped prompt byte-for-byte (asserted by a golden-string
  test in the toggle deliverable, `shorts-874`).

---

## 6. Statistical procedure (the bootstrap, fixed)

For the primary metric on the **TEST** sources:

1. Compute per-source delta `Δ_s = weighted_overlap_ON(s) − weighted_overlap_OFF(s)`
   (each arm k-averaged), paired by source.
2. **Bootstrap 95% CI of mean(Δ):** resample sources *with replacement*, `B = 10000`
   replicates, recompute `mean(Δ)` each time, report the 2.5th/97.5th percentiles.
3. Report the point estimate `mean(Δ)`, the CI, and the fraction of bootstrap replicates with
   `Δ > 0` (a one-sided posterior-style readout).
4. Tier 3 feature correlations use the same machinery: Spearman ρ per feature vs outcome,
   `B = 10000` bootstrap CI over clips, **Benjamini–Hochberg FDR at q = 0.10** across the
   feature family (we test ~8 features — control the false-discovery rate, don't cherry-pick
   the one that cleared p<0.05).

Seeds for the bootstrap resampler are fixed and recorded so every CI is reproducible.

---

## 7. Decision rule (the ship gate — committed)

The §9 corpus ships as the pipeline default **only if BOTH**:

- **G1 (Tier 2, primary):** on the **held-out TEST sources**, the bootstrap 95% CI of
  `mean(Δ weighted-overlap)` **excludes 0 in the positive direction**
  (i.e. lower CI bound > 0). A point estimate that "looks positive" with a CI straddling 0
  is a **null result** and ships nothing.
- **G2 (Tier 1, non-contradiction):** the production A/B does **not** show a CI-clean
  *negative* effect on real VVSA/retention. (It need not independently prove the win — it
  must not refute it.)

Outcomes other than ship:
- **G1 null/negative →** the honest result is *"the advice does not improve selection on this
  benchmark,"* and we report it. The corpus is not shipped. We do not go fishing in the
  secondary metrics or the DEV set for a win.
- **G1 passes, G2 contradicts →** hold; investigate transfer gap before shipping.
- Tier 3 alone never ships anything; it only **removes** anti-correlated claims from `advice.md`
  before Tier 2 runs.

A claim/feature that **reverses** sign between Tier 3 (own audience) and Tier 2 (gold market)
is flagged as a transfer-gap risk and is not relied upon.

---

## 8. Amendment log (append-only; any change after the first ablation run goes here)

| date | what changed | why | who |
|---|---|---|---|
| 2026-06-26 | initial pre-registration committed | epic `shorts-dyd` | autonomous run |
