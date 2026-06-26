# T3 Retrospective — advice features vs real audience (own catalog)

*Source CSV:* `Table data.csv` · matched **14/26** videos (12 unmatched) · bootstrap B=3000 · BH-FDR q=0.1

> Observational, small-n, confounded (title/thumbnail/topic/posting-time). Prunes anti-correlated §9 claims; never confirms the corpus (that is Tier 2).

> **Primary outcome:** avd_frac (retention proxy = avg view duration / clip duration). ρ>0 = feature tracks higher retention; ρ<0 = anti-correlated (prune candidate). `✓` = survives FDR; bracket = bootstrap 95% CI.


## §9 claim verdicts (primary outcome `avd_frac`)

| advice feature | corpus claims | ρ retention | 95% CI | verdict | reverses vs views? |
|---|:--:|---:|---|---|:--:|
| arousal_humor | ↑ helps | -0.563 | [-0.83, -0.31] | CONTRADICTS — prune candidate |  |
| arousal_density | ↑ helps | -0.432 | [-0.86, +0.18] | unsupported (CI crosses 0; small-n) |  |
| has_pivot | ↑ helps | +0.353 | [-0.21, +0.76] | unsupported (CI crosses 0; small-n) |  |
| arousal_awe | ↑ helps | +0.241 | [+0.00, +0.59] | unsupported (CI crosses 0; small-n) |  |
| opens_number | ↑ helps | -0.203 | [-0.59, +0.17] | unsupported (CI crosses 0; small-n) |  |
| arousal_anxiety | ↑ helps | -0.172 | [-0.51, +0.10] | unsupported (CI crosses 0; small-n) |  |
| jargon_density | ↓ hurts | -0.166 | [-0.66, +0.39] | unsupported (CI crosses 0; small-n) |  |
| opens_question | ↑ helps | +0.103 | [-0.20, +0.46] | unsupported (CI crosses 0; small-n) |  |
| opening_hedge | ↓ hurts | -0.065 | [-0.55, +0.37] | unsupported (CI crosses 0; small-n) |  |

*Only CONTRADICTS rows are actionable now (prune from `advice.md` before Tier 2). SUPPORTED rows survive; `unsupported` rows are simply underpowered at this n — neither kept nor cut on this evidence. ⚠ reversal = the feature helps one outcome and hurts another → transfer-gap risk, do not rely on it.*


## Outcome: `avd_frac`

| feature | ρ | 95% CI | n | FDR✓ | P(ρ>0) |
|---|---:|---|---:|:--:|---:|
| replay_quotient | +0.578 | [-0.03, +0.82] | 13 |  | 0.97 |
| payoff_offset_sec | -0.577 | [-1.00, +0.40] | 5 |  | 0.06 |
| arousal_humor | -0.563 | [-0.83, -0.31] | 14 |  | 0.00 |
| arousal_density | -0.432 | [-0.86, +0.18] | 14 |  | 0.07 |
| overall_score | +0.383 | [-0.22, +0.80] | 14 |  | 0.92 |
| has_pivot | +0.353 | [-0.21, +0.76] | 14 |  | 0.90 |
| arousal_awe | +0.241 | [+0.00, +0.59] | 14 |  | 0.97 |
| structure_score | +0.240 | [-0.35, +0.72] | 14 |  | 0.78 |
| opens_number | -0.203 | [-0.59, +0.17] | 14 |  | 0.11 |
| arousal_anxiety | -0.172 | [-0.51, +0.10] | 14 |  | 0.06 |
| jargon_density | -0.166 | [-0.66, +0.39] | 14 |  | 0.28 |
| hook_score | +0.134 | [-0.54, +0.81] | 14 |  | 0.63 |
| hook_is_question | -0.120 | [-0.69, +0.59] | 11 |  | 0.33 |
| opens_question | +0.103 | [-0.20, +0.46] | 14 |  | 0.78 |
| opening_hedge | -0.065 | [-0.55, +0.37] | 14 |  | 0.35 |
| context_score | -0.037 | [-0.64, +0.68] | 13 |  | 0.45 |
| hook_payoff_coherence | +0.000 | [-1.00, +1.00] | 5 |  | 0.40 |

## Outcome: `avd_sec`

| feature | ρ | 95% CI | n | FDR✓ | P(ρ>0) |
|---|---:|---|---:|:--:|---:|
| replay_quotient | +0.539 | [+0.02, +0.82] | 13 |  | 0.98 |
| arousal_humor | -0.508 | [-0.80, -0.24] | 14 |  | 0.00 |
| hook_is_question | -0.478 | [-0.86, +0.13] | 11 |  | 0.05 |
| arousal_density | -0.467 | [-0.91, +0.12] | 14 |  | 0.06 |
| overall_score | +0.416 | [-0.28, +0.84] | 14 |  | 0.90 |
| opens_question | +0.378 | [+0.24, +0.72] | 14 |  | 1.00 |
| context_score | -0.222 | [-0.76, +0.40] | 13 |  | 0.23 |
| has_pivot | +0.157 | [-0.40, +0.62] | 14 |  | 0.70 |
| opening_hedge | +0.065 | [-0.36, +0.51] | 14 |  | 0.59 |
| structure_score | +0.055 | [-0.54, +0.62] | 14 |  | 0.55 |
| opens_number | -0.051 | [-0.44, +0.33] | 14 |  | 0.36 |
| arousal_anxiety | -0.034 | [-0.33, +0.24] | 14 |  | 0.36 |
| arousal_awe | +0.034 | [-0.24, +0.33] | 14 |  | 0.57 |
| hook_score | -0.019 | [-0.63, +0.63] | 14 |  | 0.46 |
| jargon_density | -0.013 | [-0.50, +0.51] | 14 |  | 0.49 |
| hook_payoff_coherence | +0.000 | [-1.00, +1.00] | 5 |  | 0.40 |
| payoff_offset_sec | +0.000 | [-1.00, +1.00] | 5 |  | 0.38 |

## Outcome: `log_views`

| feature | ρ | 95% CI | n | FDR✓ | P(ρ>0) |
|---|---:|---|---:|:--:|---:|
| hook_payoff_coherence | +0.866 | [+0.73, +1.00] | 5 |  | 1.00 |
| payoff_offset_sec | +0.866 | [+0.73, +1.00] | 5 |  | 1.00 |
| overall_score | +0.579 | [+0.03, +0.88] | 14 |  | 0.98 |
| hook_score | +0.459 | [-0.09, +0.84] | 14 |  | 0.95 |
| opens_question | -0.447 | [-0.73, -0.45] | 14 |  | 0.00 |
| arousal_awe | +0.378 | [+0.24, +0.72] | 14 |  | 1.00 |
| hook_is_question | +0.299 | [-0.41, +0.85] | 11 |  | 0.79 |
| arousal_anxiety | +0.241 | [+0.03, +0.59] | 14 |  | 0.98 |
| has_pivot | -0.235 | [-0.71, +0.33] | 14 |  | 0.19 |
| jargon_density | +0.202 | [-0.33, +0.69] | 14 |  | 0.77 |
| context_score | +0.148 | [-0.47, +0.64] | 13 |  | 0.69 |
| arousal_humor | -0.126 | [-0.60, +0.38] | 14 |  | 0.33 |
| opening_hedge | -0.108 | [-0.52, +0.32] | 14 |  | 0.28 |
| opens_number | -0.101 | [-0.51, +0.32] | 14 |  | 0.31 |
| structure_score | +0.092 | [-0.48, +0.64] | 14 |  | 0.60 |
| arousal_density | +0.048 | [-0.56, +0.64] | 14 |  | 0.55 |
| replay_quotient | -0.025 | [-0.64, +0.65] | 13 |  | 0.47 |

## Outcome: `ctr`

| feature | ρ | 95% CI | n | FDR✓ | P(ρ>0) |
|---|---:|---|---:|:--:|---:|
| overall_score | +0.617 | [+0.07, +0.83] | 14 |  | 0.99 |
| arousal_anxiety | +0.447 | [+0.45, +0.73] | 14 |  | 1.00 |
| jargon_density | +0.418 | [-0.16, +0.80] | 14 |  | 0.93 |
| opening_hedge | -0.367 | [-0.73, +0.10] | 14 |  | 0.05 |
| replay_quotient | -0.360 | [-0.88, +0.35] | 13 |  | 0.14 |
| arousal_humor | -0.321 | [-0.71, +0.10] | 14 |  | 0.07 |
| opens_question | -0.310 | [-0.64, -0.10] | 14 |  | 0.00 |
| hook_payoff_coherence | +0.289 | [-0.97, +1.00] | 5 |  | 0.64 |
| payoff_offset_sec | -0.289 | [-1.00, +0.97] | 5 |  | 0.18 |
| structure_score | -0.277 | [-0.69, +0.29] | 14 |  | 0.14 |
| hook_score | -0.249 | [-0.74, +0.39] | 14 |  | 0.21 |
| arousal_density | +0.197 | [-0.44, +0.77] | 14 |  | 0.72 |
| hook_is_question | +0.179 | [-0.41, +0.76] | 11 |  | 0.67 |
| has_pivot | -0.118 | [-0.65, +0.47] | 14 |  | 0.33 |
| arousal_awe | +0.103 | [-0.20, +0.45] | 14 |  | 0.78 |
| opens_number | -0.101 | [-0.50, +0.31] | 14 |  | 0.27 |
| context_score | -0.019 | [-0.63, +0.63] | 13 |  | 0.47 |

## Unmatched CSV videos (no delivered-file join)

- [1617 v] the-one-thing-chatgpt-could-not-build
- [1494 v] how-mrbeast-got-his-name
- [1335 v] gold-stars-made-kids-quit-drawing
- [1213 v] dopamine-is-not-a-reward-molecule
- [1159 v] he-used-more-scaffolding-than-the-olympics
- [1025 v] the-phone-habit-nobody-chooses
- [9 v] the-productivity-dragon
- [6 v] what-is-ai-s-real-role-on-a-dev-team
- [5 v] why-speed-isnt-what-bosses-really-want
- [4 v] starlink-works-in-antarctica
- [4 v] why-the-fastest-coders-arent-the-best
- [3 v] mrbeast-wants-ozempic-in-food

---
*Interpretation:* a §9 claim is a **prune candidate** when its feature's CI excludes 0 in the WRONG direction on the primary outcome (e.g. a positive-claimed feature with ρ<0, CI not crossing 0). A claim with CI crossing 0 is simply unsupported here — small-n; it neither holds nor fails. Tier 2 (gold set) is the confirmatory test.
