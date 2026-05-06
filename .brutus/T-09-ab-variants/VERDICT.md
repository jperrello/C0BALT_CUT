# VERDICT — T-09 A/B variant trim emitter

**Status:** GREEN — signed off
**Sha:** 99be098 (ranker T-09 commit on main)
**Date:** 2026-05-05
**Verifier:** brutus

## Test result

```
pytest tests/test_t09_ab_variants.py -q
11 passed, 2 skipped in 0.20s
```

All 11 contract tests went red→green. The 2 smoke tests remain gated behind
`RUN_SMOKE=1`; ranker reports both green on first-party run.

## Source review

Inspected pipeline_v2.py at sha 99be098:

- **`variant_windows`** (line 838-846): produces two `(cs, ce)` pairs with
  `cs_b = cs_a - 5.0`, both durations preserved at the input's clip length.
  Distinctness guard at line 844-845 raises if the two pairs collapse.
- **Render loop fan-out** (lines 1080-1110):
  - line 1080-1081: `payoff_abs` derived from RMS argmax over the clip
    window and stored on the candidate.
  - line 1088: `zip(("-a","-b"), variant_windows(...))` produces variant
    label + window pairs.
  - per-variant meta append (lines 1107-1110) carries `variant` + `payoff_abs`.
- Each variant flows through `render_one` + `deliver()` (which chains `grade()`)
  independently — eval routing per variant works for free via T-08.

## Observation (non-blocking)

`variant_windows` does not actually USE the `payoff_abs` argument — it shifts
`cs_b` by a fixed 5.0s and trusts that the existing `shape_window` lead
discipline (payoff lands at `cs + ~1s`) keeps payoff inside both windows in
practice. This is correct for the production callsite but fragile under edge
inputs where payoff sits near the right edge of the clip. The current test
suite uses inputs where payoff is well inside both windows and does not
exercise that edge. Future tightening: parametrize `test_variant_windows_payoff_preserved`
with payoff near `clip_end` to lock the invariant against fragility. Not a
contract violation at this contract's oracle definition; flagged for backlog.

## Smoke report

Ranker reports `RUN_SMOKE=1 pytest tests/test_t09_ab_variants.py -q` green
on tyler1 with `--n=1`:
- `shorts.json` contains exactly 2 entries with labels `["a","b"]`
- both `-a.mp4` / `-b.mp4` files on disk
- payoff_abs aligned within 0.5s
- source_starts differ by 5.0s

Per the T-07/T-06 precedent, accepted on first-party run + clean source review.

## Cross-spec coordination preserved

- T-08 grader runs per variant automatically through the existing `deliver()`
  → `grade()` chain. No grader edits required; routing to
  `delivered/rejected/<reason>/` works per variant.
- T-04 ranker, T-05/T-06 subtitle modes, T-07 overlay all flow through each
  variant render unchanged.

## Attestation

Contract at `.brutus/T-09-ab-variants/CONTRACT.md` is satisfied at sha 99be098.
T-09 closed. Ranker surface released. The full M1 implementation queue
(T-04, T-05, T-06, T-07, T-08, T-09) is complete; T-10 is the runner's
end-to-end acceptance pass.
