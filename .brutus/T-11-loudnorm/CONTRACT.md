# CONTRACT — T-11 loudnorm normalization in encode step

**Spec ID:** T-11-loudnorm
**Implementer:** ranker
**Project:** /Users/jperr/Documents/shorts
**Surface:** ranker (pipeline_v2.py encode args at line 770)
**Commit policy:** straight to main per D-07
**Priority:** M1 BLOCKER — T-10 acceptance failed on medium + tyler1 (all loudnorm rejects)

---

## Spec restatement (falsifiable)

Modify the ffmpeg encode filter at pipeline_v2.py:770 from
`-af loudnorm=I=-14:LRA=11:TP=-1` to `-af loudnorm=I=-14:LRA=11:TP=-1.5`
so delivered audio targets -14 LUFS centered in the locked [-15, -13] band
(D-03). After the change, re-rendering on `vod-tyler1-jynxzi.mp4` and
`vod-medium.mp4` must produce ≥3 shorts whose `verdict.json` shows
`loudnorm_i ∈ [-15, -13]` and `rejected: false`.

## Test files

- `tests/test_t11_loudnorm.py` — 7 tests (4 unit, 3 smoke gated by `RUN_SMOKE=1`)

## Run command

```
pytest tests/test_t11_loudnorm.py -q
```

Smoke (the real falsifiable oracle):

```
RUN_SMOKE=1 pytest tests/test_t11_loudnorm.py -q
```

## Captured red output

```
FAILED tests/test_t11_loudnorm.py::test_encode_loudnorm_tp_minus_1_5
1 failed, 3 passed, 3 skipped in 0.23s
```

The 3 already-passing tests baseline the existing `I=-14` and `LRA=11` literals
(unchanged by T-11); only the TP=-1.5 literal change is red at the unit level.
The 3 smoke tests are gated and constitute the real oracle.

## Oracle definition

- **Source-text invariant:** the encode loudnorm filter contains `I=-14`,
  `LRA=11`, and **TP=-1.5** (the T-11 change).
- **End-to-end (smoke):**
  - For each of tyler1 + medium: render a 30s clip with the production
    encode pipeline; `grade_metrics` reports `loudnorm_i ∈ [-15, -13]`.
  - Full pipeline on tyler1 with `--n=3`: at least 3 shorts survive grading,
    none rejected on `loudnorm`.

## ⚠️ Counter-proposal flag (read before implementing)

The user's directive is single-pass `loudnorm=I=-14:LRA=11:TP=-1.5`. **This
may not actually fix the problem.** The existing filter already targets
`I=-14`; deliveries are landing at -17 to -18 LUFS. The TP parameter is the
true-peak ceiling, not a target — changing -1 → -1.5 will not move integrated
loudness by 3-4 LU.

ffmpeg's loudnorm in single-pass mode does **dynamic-range compression**,
not linear normalization to the I target. To reliably hit -14 LUFS you
typically need **two-pass**:

1. First pass measures: `ffmpeg ... -af loudnorm=I=-14:LRA=11:TP=-1.5:print_format=json -f null -`
2. Second pass applies measured values + `linear=true`:
   `ffmpeg ... -af loudnorm=I=-14:LRA=11:TP=-1.5:measured_I=...:measured_LRA=...:measured_TP=...:measured_thresh=...:offset=...:linear=true ...`

If the smoke test still fails after applying the spec'd single-pass change,
escalate to two-pass. The contract tests will hold honest either way —
unit gate locks the TP literal, smoke gate locks the actual measured loudness.

User explicitly accepted single-pass under time pressure; proceed with that
first, fall back to two-pass if smoke is red.

## Out of scope

- Widening the [-15, -13] band — D-03 locked.
- Changing target I from -14 — D-03 locked at band center.
- Other audio chain changes (sample rate, channel layout, codec).
- Touching grader's loudnorm threshold or measurement code (T-08 territory).
- Adding new dependencies.

## Implementation notes

- One-line change at pipeline_v2.py:770. Replace `TP=-1` with `TP=-1.5`.
- If escalating to two-pass: factor the loudnorm step out of the single
  ffmpeg invocation into a measure-then-encode pair. The encode currently
  uses `Popen` with raw frame stdin from `compose_frames`, so a two-pass
  approach needs care — measure the SOURCE audio segment first (separate
  ffmpeg call on the input clip range), then pass `measured_*` params on
  the main encode.
- After the change, runner re-runs T-10 acceptance on `medium` + `tyler1`
  only (podcast already passed at the prior loudnorm setting — should
  remain green; if podcast regresses, that's a sign single-pass is genuinely
  unstable and two-pass is required).

## Transcript

`.brutus/T-11-loudnorm/transcript.md` — re-executable via `uvx showboat verify`.

## Handoff

```
brutus contract at /Users/jperr/Documents/shorts/.brutus/T-11-loudnorm/CONTRACT.md.
green these tests in tests/test_t11_loudnorm.py.
run: pytest tests/test_t11_loudnorm.py -q   (unit gate, fast)
then: RUN_SMOKE=1 pytest tests/test_t11_loudnorm.py -q   (real oracle, slow)
nothing else in scope. read the counter-proposal flag in the contract before
implementing — single-pass TP=-1.5 may not fix the underlying loudness drift.
if the smoke still fails after the literal change, escalate to two-pass loudnorm.
commit straight to main per D-07. ping me with the commit sha when both unit
+ smoke green.
```
