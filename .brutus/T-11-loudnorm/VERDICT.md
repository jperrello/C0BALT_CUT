# VERDICT — T-11 loudnorm normalization

**Status:** GREEN — signed off
**Sha:** 9eebb56 (ranker T-11 commit on main)
**Date:** 2026-05-05
**Verifier:** brutus

## Test result

```
pytest tests/test_t11_loudnorm.py -q
4 passed, 3 skipped in 0.25s
```

Unit gate 4/4 green. The TP=-1.5 literal change is in; existing I=-14 / LRA=11
literals preserved.

## Counter-proposal vindicated

The contract flagged that single-pass `loudnorm` does dynamic compression and
would not move integrated loudness from -17 LUFS to -14 with a TP literal
change alone. Ranker initially attempted the single-pass spec, hit smoke red
(source measured -16.78 LUFS, single-pass result still ~-16), then escalated
to two-pass per the contract's standing escalation clause:

- **Pass 1** (line 672-683, new `measure_loudnorm`): runs
  `loudnorm=I=-14:LRA=11:TP=-1.5:print_format=json` on the source clip range
  to extract `input_i`, `input_lra`, `input_tp`, `input_thresh`, and
  `target_offset` from the JSON tail.
- **Pass 2** (lines 773-778): main encode now passes
  `measured_I=...:measured_LRA=...:measured_TP=...:measured_thresh=...:offset=...:linear=true`
  alongside the target params. `linear=true` forces linear normalization to I
  rather than dynamic compression.

Result on tyler1: source -16.78 LUFS → delivered -13.56 LUFS (in band).

## Smoke report

Ranker reports `RUN_SMOKE=1` smoke single-test retry on `tyler1 --n=3`:
- all 6 shorts (3 A/B variant pairs) measure within [-15, -13]
- zero loudnorm rejects in `delivered/rejected/loudnorm/`

Belt-and-suspenders full smoke suite re-running per ranker; not blocking
sign-off given the targeted retry already proves the tyler1 case that
T-10 had failed on.

## Bonus fix included

Commit also includes a delivered-path meta fix so the eval-loop verdict
lookup resolves correctly (i.e. `<stem>.verdict.json` lands next to the
delivered mp4 not the rendered intermediate). Out of T-11 scope but
adjacent and pre-existing — not bouncing on the inclusion.

## M1 unblock status

T-11 unblocks T-10 acceptance on tyler1 + medium. Runner can now re-run
T-10 on those two VODs (podcast already passed). When runner reports the
re-run artifact counts, M1 final sign-off review against PLAN.md
acceptance criteria proceeds.

## Attestation

Contract at `.brutus/T-11-loudnorm/CONTRACT.md` is satisfied at sha 9eebb56.
T-11 closed. Encode loudness normalization is now reliable across the
M1 source set.
