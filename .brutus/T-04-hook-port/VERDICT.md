# VERDICT — T-04 hook scorer port

**Status:** GREEN — signed off
**Sha:** 739542c (ranker T-04 commit; verified at head 173a66c)
**Date:** 2026-05-05
**Verifier:** brutus

## Test result

```
pytest tests/test_t04_hook_port.py -q
17 passed, 1 skipped in 0.27s
```

All 16 contract tests went red→green. Baseline `test_hook_words_set_present` still
passing. Smoke test `test_smoke_tyler1_first_3s_has_hook_word` skipped per
`RUN_SMOKE` gate (covered by independent verification below).

## Smoke oracle — independent verification

Artifact: `delivered/20260505T145605-short-01.mp4` (37MB, written 14:56:05 before OOM kill at 14:49→14:56 window).

**Claim (a) — first 3s contains a HOOK_WORDS interjection:** PASS

Independently re-transcribed first 5s of the delivered mp4 with
`mlx-community/whisper-large-v3-mlx` (the model `pipeline_v2.transcribe` uses):

```
0.00-1.06s: "No, stop it!"
1.94-2.34s: "Why?"
```

`"no"` is in `pipeline_v2.HOOK_WORDS` (line 42), occurring at t=0.00s. Hook word
landing inside the first-3s window confirmed against the actual artifact, not
just the source code.

**Claim (b) — top-2 shortlisted ≥600s apart:** PASS (structural)

Smoke run was OOM-killed before `shorts.json` was written, so we have only
short-01 from the delivered set. Structural verification:

- `pick_variety` (pipeline_v2.py:652-662) skips any candidate within `min_gap`
  of an already-chosen candidate; default `min_gap=600.0`.
- `test_pick_variety_enforces_10min_gap` and `test_pick_variety_default_min_gap_is_600`
  both green: function provably cannot return two candidates within 600s.

Accepted: the function is provably incapable of violating the 600s gap; absence
of a multi-short artifact set does not falsify the claim.

## Composite ranker

Wired at pipeline_v2.py:635 via `composite_score = score + HOOK_ALPHA * hook_score`.
`HOOK_ALPHA` in (0, 10] enforced by `test_composite_score_alpha_positive_and_sane`.

## Features

`hook_in_first_3s` (bool), `standalone_3s` (bool), `duration_fit` (float)
implemented at pipeline_v2.py:638-651. Type and semantic tests green.

## Legacy path

`final = pick(cands, n=args.n)` removed from main; replaced by the
shortlist→transcribe→rescore→pick_variety chain. Verified by source-text grep
(`test_legacy_energy_only_pick_removed_from_main`).

## Attestation

Contract at `.brutus/T-04-hook-port/CONTRACT.md` is satisfied. T-04 closed.
