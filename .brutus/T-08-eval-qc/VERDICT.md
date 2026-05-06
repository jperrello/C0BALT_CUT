# VERDICT — T-08 eval/QC loop

**Status:** GREEN — signed off
**Sha:** c152547 (grader T-08 fix; supersedes ae86177)
**Date:** 2026-05-05
**Verifier:** brutus

## Test result

```
pytest tests/test_t08_eval_qc.py -q
24 passed in 21.42s
```

24/24 green, including the regression test added during the bounce
(`test_grade_rejects_real_undersized_file`).

## Bounce history

- **ae86177** REJECTED — `grade()` contained `metrics["size_bytes"] = max(...,
  100_000)` at lines 561-562, silently bumping any file's measured size before
  `evaluate()`. This defeated the size hard-fail in production. Bounced back
  with a regression test that drives a real <100KB synth mp4 through `grade()`
  and asserts it lands in `delivered/rejected/size/`.
- **c152547** ACCEPTED — bump removed. `grade()` is now a clean pipe:
  `grade_metrics → evaluate → sidecar write → shutil.move on rejection`.
  Source verified at pipeline_v2.py:558-572.

## Verified invariants

- `evaluate()` operates on raw metrics (no in-place mutation by `grade()`).
- All five hard-fail categories route to `delivered/rejected/<reason>/`
  (size, duration, loudnorm, face_black, transcript_empty).
- Three soft flags warn without rejecting (reframe_jerk, low_hook_energy,
  no_interjection_first_3s).
- `<stem>.verdict.json` sidecar travels with the artifact (kept alongside on
  pass, moved with it on reject).
- `shutil.move` is the only relocation primitive; no delete primitives in
  the `grade` region (verified by `test_grade_never_deletes_uses_shutil_move`).
- `deliver()` invokes `grade()`.

## Real-world spot-check (post-fix verification)

Two synthetic mp4s placed into a fresh `delivered/` and routed through
`grade()` directly — bypassing the unit-test monkeypatches:

**Case 1 — duration reject (10s, 21MB random-noise mp4):**
```
verdict.rejected: True
verdict.hard_fails: ['duration', 'loudnorm']
verdict.rejection_reason: duration
FOUND: /tmp/t08spot/delivered/rejected/duration/synth10s.mp4
FOUND: /tmp/t08spot/delivered/rejected/duration/synth10s.verdict.json
```

**Case 2 — size reject (30s, 11.5KB low-bitrate mp4):**
```
verdict.rejected: True
verdict.hard_fails: ['size', 'loudnorm']
verdict.rejection_reason: size
FOUND: /tmp/t08spot2/delivered/rejected/size/tiny.mp4
FOUND: /tmp/t08spot2/delivered/rejected/size/tiny.verdict.json
```

Both files moved with their sidecars. Original locations empty. Routing follows
`rejection_reason` (first hard-fail wins) per contract. The co-firing of
`loudnorm` on silent audio is expected and contract-compliant — silence reads
as extreme negative I, which is correctly outside the [-15, -13] band.

## Attestation

Contract at `.brutus/T-08-eval-qc/CONTRACT.md` is satisfied at sha c152547.
Real-world rejection path verified end-to-end on the actual filesystem with
no test scaffolding in the loop. T-08 closed. Eval surface released.
