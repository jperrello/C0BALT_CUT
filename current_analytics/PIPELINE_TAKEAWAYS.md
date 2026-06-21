# @C0BALT_CUT — 28-Day Analytics → Pipeline Takeaways

_Window: 2026-05-23 → 2026-06-19. n=19 uploaded, 101 produced. Generated from `Table data.csv`, `Chart data.csv`, `Totals.csv` + the `output/` artifact tree + a code-grounded, adversarially-verified analysis pass._

## Snapshot
- **14,919 views · 218 likes (1.46%) · 2 shares · 4 subscribers.**
- **19 of 101 produced shorts were uploaded (19%).** 82 finished shorts sit unreleased.
- **Bimodal lottery:** 12 clips hit **657–1,834** views; 7 died at **2–6** views. *Nothing in between.* A clip either gets the algorithmic push or it doesn't.
- **No evergreen tail:** 86–100% of every clip's lifetime views land in days 1–3. Channel views = posting cadence × hit-rate, nothing else.

## Read the caveats first
This is **n=19 uploads** with heavy confounding. Niche, source-fame, publish-date, and pipeline-version all move together (the newest clips are also the science clips from the most famous sources made by the newest pipeline). The CSVs contain **no impressions, CTR, average-view-duration, or swipe-away** — "Engaged-view-rate" (engaged ÷ views) is used here as a *view-quality proxy for retention*, not true retention. Engaged-rate on the 7 dead clips is statistical noise (1–3 engaged of 2–6 views) and is excluded everywhere. Every claim below was run through an adversarial refutation pass; the confidence tags reflect what survived.

---

## TIER 1 — High confidence, low risk, do now

### 1. Cadence is the #1 lever — never repeat the 7-day gap. _(verified, unconfounded)_
The channel earned **~0 views on Jun 3–9** for one reason: nothing was published. With no tail, every dark day is permanent lost reach. You have **82 finished shorts on disk** — there is zero production reason for a dark day.
- **Pipeline correlation:** not a skill bug — an ops/scheduling gap. The pipeline is *over-supplying* inventory relative to publishing.
- **Action:** publish on a fixed daily cadence from the existing backlog. This alone would have erased ~7 zero-view days this window.

### 2. The cold-open B-roll regression — the one retention finding that is NOT confounded. _(vision-audited, high value)_
Vision audit of 3 high-retention vs 3 low-retention clips found the **low retainers have concrete cold-open defects the high retainers don't** — independent of niche:

| Clip | Eng% | Cold-open defect found in frames 0–2s |
|---|---|---|
| huberman-fear / -dopamine / gold-stars | 52–58% | ✅ Textbook: frame 1 = face mid-sentence, top-banner glitch title, b-roll pattern-interrupt by ~2s, strong curiosity hook |
| `how-mrbeast-got-his-name` | 39% | ❌ Opens on **B-roll (Xbox console + animal), no face in first 2s**; title rendered as a **centered block, not the top banner**; **source credit appears at t=0** (should be final 3s only); **double captions** (b-roll's own burned-in subtitle stacked under karaoke) |
| `fans-say-caseoh-saved-their-lives` | 31% | ❌ Opens on an **Instagram-DM screenshot b-roll**, the creator's face withheld until ~2s; opening line "i've got dms on instagram" is flat setup, no curiosity gap |
| `caseoh-s-card-declined…` | 44% | ⚠️ Structure OK but opens on a **mid-sentence fragment** caption ("saw was when you were") and the **wrong person on screen** (guest, not CaseOh) |

The pattern: **b-roll cutaways and weak opening lines are landing in the first ~2 seconds, burying the face and the hook** — exactly the swipe-rate leak the cold-open design exists to prevent.
- **Pipeline correlation:**
  - `broll-pick` / `broll-composite` — **forbid any cutaway in the first ~2.0–2.5s** so the cold open is always a face mid-sentence (the spec's stated intent). Today a cutaway window can open at t=0.
  - `how-mrbeast-got-his-name` shows three likely **bugs to investigate**: title rendered as a centered card instead of the `TITLE_ANCHOR_FRAC≈0.135` banner, source credit appearing at the open instead of only in `CREDIT_TAIL`, and the b-roll's own burned-in subtitles not being stripped (double caption band).
  - `verify-bookends` / `pick-segments` opening-line — the CaseOh clips open on a flat setup clause or a mid-sentence fragment; the opener guard should reject "i've got dms on instagram"-class non-hooks and fragment openers more aggressively.

### 3. Prune the proven-dead source seeds. _(supported; this is the *narrow* version of the fame claim)_
Every sub-10-view clip came from a **losing topic**: generic productivity how-tos, an unknown TEDx software talk, and the `#aivideo` AI-dev experiment. But "fame wins" was **weakened** in review — the **2nd-best source overall (`science-making-breaking-habits`, 2/2 hits, 2,233 views) is non-marquee**. So the signal is **topic**, not raw fame.
- **Pipeline correlation:** `scout-sources/niches.txt` currently seeds ~half losing categories.
  - **Remove/replace** line 9 `productivity psychologist interview` and line 10 `ai software engineering talk` (near-verbatim matches to the dead clips).
  - **Reconsider** the generic-explainer seeds (8, 14, 15, 16, 17, 18) — no named anchor, the 2–6-view failure mode.
  - **Add a `caseoh` seed** — it's a proven hit (2/2, drove 2 of 4 subs) with **no seed line at all**.
  - **Do NOT add an explicit fame weight to `score.py`** — it would have *suppressed* the non-marquee chart-topper, and it conflicts with `score.py:49` where `outlier = views/subs` already inversely penalizes big channels.

---

## TIER 2 — Directionally supported, act with care

### 4. Constraint is publishing **cadence-and-selection**, not raw production. _(weakened from "throughput"; core survives)_
19% upload share is real, but the backlog is **62% one source** (MrBeast/Theo-Von: 55 made, 4 uploaded) — that's over-production of one vein, not a broad reservoir of marquee gold. And **37% of upload slots died** on generic/non-marquee clips. The fix is **publish better, not just more**: pull daily from winning topics (named entertainment pods + science/self-improvement), cherry-pick the MrBeast 55 rather than dumping them.
- Caveat that capped this: with a **1-sub-per-3,729-views** floor, even 5× reach ≈ ~17 subs — growth is partly conversion-bound, so "clear the backlog" is a reach play, not a subscriber play.

### 5. `<40%` engaged-view-rate as a soft QC investigate-flag. _(defensible heuristic, not a law)_
Top retainers are Huberman/science (51.2% mean); the `<40%` floor cleanly flags the three weakest cold-opens (mrbeast-name 39%, chatgpt-build 32.5%, fans-caseoh 31.1%) — the same clips the vision audit independently flagged for defects.
- **Pipeline correlation:** add a **non-fatal diagnostic** (in the spirit of `visual-cadence`) that WARNs when a delivered clip's projected hook is weak, or simply track engaged-rate per upload and re-audit the cold-open of anything under 40%. Do **not** gate/reject on it.

---

## TIER 3 — Hypotheses to test, NOT yet conclusions

### 6. "Recent retention levers raised retention" — **unproven** (confounded). _(weakened, high confidence)_
The two newest clips do hold the highest engaged-rates (54%, 58%) and Jun14+ hits average 47.7% vs 43.0% — **but niche fully absorbs it.** Science clips out-retain everything by ~10pt (51.2% vs 41.1%) *regardless of version*, and the newest clips are the science/marquee clips. Pipeline version is perfectly collinear with niche, fame, and date.
- **To actually credit the glitch-title / jump-cut-coverage / end-card levers:** run a **within-niche A/B** — same Huberman-tier source, old vs new pipeline — measured on **real Audience Retention / AVD**, not engaged-rate.

### 7. "The CTA/end-card convert poorly" — **not supported by this data.** _(weakened, high confidence)_
1.46% like-rate sits **inside the normal small-channel Shorts band (~1–3%)**, and the CTA/like-subscribe/end-card are identical deterministic steps on every video with **no A/B or no-CTA control** — so poor conversion can't be pinned on the overlays. The "subs are niche-bound" sub-claim is **refuted**: CaseOh (comedy) drove **2 of 4 subs**, and at n=4 the 2/2/0/0 split is Poisson noise.
- **Action:** don't rip out or rebuild the CTA based on this window. If you want to test it, you need an A/B, not these CSVs.

---

## What to pull next (to break the confounds)
The single highest-value follow-up is exporting, per video: **Impressions, Impressions CTR, Average View Duration / % viewed, and the Audience-Retention curve** (esp. the 0–3s swipe-away cliff). Those convert every Tier-3 "hypothesis" into a measurable, niche-controlled answer and would let the cold-open levers be credited or killed on evidence.

## One-line summary
**Post daily from the backlog, fix the b-roll/opener that's burying the face in the first 2 seconds, and cut the dead generic-explainer source seeds — those three are real and actionable. Everything about "which lever raised retention" and "the CTA is broken" is confounded noise at n=19; don't act on it without retention-curve data.**
