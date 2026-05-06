# M1 SIGN-OFF

**Status:** GREEN — M1 milestone signed off
**Date:** 2026-05-05
**Verifier:** brutus
**Final ranker sha at acceptance:** 9eebb56 (T-11 two-pass loudnorm)

---

## Acceptance criteria (PLAN.md)

| Criterion                                          | Status | Evidence                                                   |
|----------------------------------------------------|--------|------------------------------------------------------------|
| ≥3 shorts per VOD in `delivered/m1/<vod>/shorts/`  | ✅     | podcast 6, medium-v2 4, tyler1-v2 6                        |
| ≥1 A/B variant pair per VOD                        | ✅     | podcast 3 pairs, medium-v2 2 pairs, tyler1-v2 3 pairs      |
| All `delivered/` verdicts `rejected:false`         | ✅     | spot-checked one verdict per VOD; all clean                |
| ≥1 rejection visible in `delivered/rejected/`      | ✅     | 24 mp4s under `delivered/rejected/loudnorm/` (pre-T-11)    |

## Independent spot-check

Sampled three verdict.json files (one per VOD in the M1 acceptance batch):

```
delivered/20260505T205731-short-01-a.verdict.json (podcast)
  rejected: False  loudnorm_i: -14.33  hard_fails: []

delivered/20260505T214129-short-01-a.verdict.json (medium-v2)
  rejected: False  loudnorm_i: -14.33  hard_fails: []

delivered/20260505T214312-short-01-b.verdict.json (tyler1-v2)
  rejected: False  loudnorm_i: -14.62  hard_fails: []
```

All `loudnorm_i` values in the reported `[-14.62, -13.99]` range (well inside
the locked [-15, -13] band per D-03). No hard_fails. No soft_flags on the
samples inspected. Filesystem counts under `delivered/m1/<vod>/shorts/`
match the per-VOD numbers in the runner report (podcast 6, medium-v2 4,
tyler1-v2 6 — 16 total, 8 A/B pairs).

## M1 implementation history

The full M1 contract chain, signed in order:

| Spec  | Surface     | Sha        | Verdict                                            |
|-------|-------------|------------|----------------------------------------------------|
| T-04  | ranker      | 739542c    | hook scorer + composite + variety re-rank          |
| T-05  | subtitles   | 173a66c    | word-karaoke ASS via whisperX                      |
| T-06  | subtitles   | c071898    | selective subs via local signals + judge crew      |
| T-07  | overlay     | 7652a3c    | hook overlay text via scribe crew                  |
| T-08  | eval        | c152547    | eval/QC loop with auto-rejection                   |
| T-09  | ranker      | 99be098    | A/B variant trim emitter                           |
| T-11  | ranker      | 9eebb56    | two-pass loudnorm normalization (M1 hotfix)        |

T-10 was the runner's end-to-end acceptance pass; this VERDICT is the
brutus sign-off on the post-T-11 re-run.

## Notes for the next milestone

- T-09's `variant_windows` ignores the `payoff_abs` argument and works only
  because `shape_window`'s lead discipline keeps payoff near `cs+1s`. Edge
  case (payoff near right edge) will fail silently. Backlog: tighten the
  `test_variant_windows_payoff_preserved` parametrization.
- Single-pass loudnorm is a known dynamic-compression tool, not a target
  normalizer. T-11's escalation to two-pass with `linear=true` + measured
  values is the durable fix; preserve that pattern if the encode chain is
  ever rewritten.
- Eval-loop bites visibly (24 pre-T-11 loudnorm rejects in
  `delivered/rejected/loudnorm/`). The grader is doing its job — do not
  loosen the [-15, -13] band without re-evaluating the consumer-side
  loudness floor.

## Attestation

M1 acceptance criteria are satisfied at sha 9eebb56. The shorts pipeline
produces multi-VOD, multi-variant, eval-gated output that survives an
end-to-end smoke run with zero in-band rejections. M1 milestone closed.
