# CONTRACT — T-08 eval/QC loop with auto-rejection

**Spec ID:** T-08-eval-qc
**Implementer:** grader
**Project:** /Users/jperr/Documents/shorts
**Surface:** eval (pipeline_v2.{evaluate,grade_metrics,grade}, deliver() wire-up)
**Commit policy:** straight to main per D-07
**Status:** **PRE-STAGED — DO NOT HAND OFF YET**. Subtitler released after T-05 sign-off; grader can claim then.

---

## Spec restatement (falsifiable)

After every render, a grader runs metrics on the delivered mp4 and writes a
`<stem>.verdict.json` sidecar. **Hard fails** auto-move the artifact to
`delivered/rejected/<reason>/` via `shutil.move` (never delete). **Soft flags**
warn in the verdict and keep the artifact in `delivered/`. The grader is wired
into `pipeline_v2.deliver()` so QC runs automatically on every render.

### Hard fails (reject + move)

| Reason             | Subdir                              | Trigger                                    |
|--------------------|--------------------------------------|--------------------------------------------|
| `size`             | `delivered/rejected/size/`           | `size_bytes < 100_000`                     |
| `duration`         | `delivered/rejected/duration/`       | `duration_s < 25.0` or `duration_s > 65.0` |
| `loudnorm`         | `delivered/rejected/loudnorm/`       | `loudnorm_i < -15.0` or `> -13.0`          |
| `face_black`       | `delivered/rejected/face_black/`     | `face_tile_black_frac > 0.5`               |
| `transcript_empty` | `delivered/rejected/transcript_empty/` | `transcript_words == 0`                  |

### Soft flags (warn + keep)

- `reframe_jerk` — reframe x-signal second-derivative above threshold
- `low_hook_energy` — hook-window energy z-score below threshold
- `no_interjection_first_3s` — `hook_in_first_3s` is False

## Required public API

- `pipeline_v2.evaluate(metrics: dict) -> dict` — pure function. Returns:
  ```python
  {"metrics": <input>, "hard_fails": [str, ...], "soft_flags": [str, ...],
   "rejected": bool, "rejection_reason": str | None}
  ```
- `pipeline_v2.grade_metrics(path: Path) -> dict` — slow path: ffprobe duration,
  loudnorm I via `ffmpeg -af loudnorm=print_format=json`, face-tile black
  fraction via OpenCV mean luma on the FACE_TILE region, transcript via
  mlx-whisper (reuse existing `transcribe`).
- `pipeline_v2.grade(path: Path) -> dict` — entrypoint: calls `grade_metrics`,
  then `evaluate`, writes `<stem>.verdict.json` next to the mp4, and on
  `rejected=True` `shutil.move`s both files to `delivered/rejected/<reason>/`.
- `pipeline_v2.deliver()` — must call `grade(dst)` after the existing copy.

## Test files

- `tests/test_t08_eval_qc.py` — 23 tests (all unit, fast; no `RUN_SMOKE` gating).
  Synthetic mp4s produced via `ffmpeg lavfi color/anullsrc` keep the suite cheap.

## Run command

```
pytest tests/test_t08_eval_qc.py -q
```

## Captured red output

```
23 failed in 1.44s
```

All failures are `AttributeError` on `evaluate` / `grade_metrics` / `grade`,
or `AssertionError` on missing source-text wire-up. None are import errors,
typos, or setup faults. Red shape correctly says "the behavior is missing."

## Oracle definition

- **Pure evaluator semantics** locked by parametrized tests: every hard-fail
  category is exercised at boundary and beyond; every soft-flag category is
  exercised in isolation and must NOT reject.
- **Loudnorm band** locked at [-15, -13]: -15.0, -14.0, -13.0 pass; -15.01 and
  -12.99 reject.
- **Duration band** locked at [25, 65]: 25.0, 45.0, 65.0 pass; 24.99 and 65.01
  reject.
- **Move semantics:** rejected artifact + sidecar both end up under
  `delivered/rejected/<reason>/`; original location is empty after.
- **Never-delete invariant:** source-grep over the `def grade` region must
  contain `shutil.move` and must NOT contain `os.remove`, `.unlink(`,
  `shutil.rmtree`, or `os.unlink`.
- **deliver() wire-up:** source-grep over `def deliver` region must reference
  `grade(`.
- **Reason-name stability:** all five reason strings (`size`, `duration`,
  `loudnorm`, `face_black`, `transcript_empty`) appear in source.
- **End-to-end smoke** (`test_smoke_real_metrics_on_synth_mp4_rejects_short`):
  real `grade_metrics` on a synthetic 10s mp4 reports `duration_s ≈ 10.0` and
  `evaluate` produces `rejected=True` with `"duration"` in `hard_fails`.

## Out of scope

- The render path, ranker, or subtitle code — do NOT touch
  `score_scenes`, `pick_variety`, `composite_score`, `render_one`, `write_ass`,
  `write_ass_word`, `align_words`, `transcribe` (beyond reading them).
- Modifying `DELIVER_DIR` or the existing copy semantics in `deliver()`. Only
  the post-copy hook is in scope.
- Adding new dependencies. Use ffmpeg/ffprobe (already present), OpenCV
  (already imported), mlx-whisper (already wrapped).
- Tuning the soft-flag thresholds — pick reasonable defaults; test only
  asserts that extreme inputs trip the flag.
- Anything in pipeline.py (v1).

## Implementation notes

- `loudnorm` measurement: `ffmpeg -i in.mp4 -af loudnorm=print_format=json -f null -` ;
  the JSON in stderr's tail has `input_i`. Parse with a tail-line slice.
- Face-tile black fraction: sample N frames (8 is plenty), crop to
  `[FACE_TILE_Y:FACE_TILE_Y+FACE_TILE_S, FACE_TILE_X:FACE_TILE_X+FACE_TILE_S]`,
  mean luma < threshold (e.g. 16/255) → black.
- `transcript_words`: count of whitespace tokens across all segments returned
  by `transcribe()`.
- `evaluate` should be pure and side-effect-free; `grade` is the only place
  with filesystem mutation.
- `<stem>.verdict.json` naming: if mp4 is `foo-short-01.mp4`, sidecar is
  `foo-short-01.verdict.json`.

## Transcript

`.brutus/T-08-eval-qc/transcript.md` — re-executable via `uvx showboat verify`.

## Handoff

**HOLD.** Do not dispatch to grader until parent confirms T-05 sign-off and
releases the pipeline_v2.py write lock from subtitler. When released:

```
brutus contract at /Users/jperr/Documents/shorts/.brutus/T-08-eval-qc/CONTRACT.md.
green these 23 tests in tests/test_t08_eval_qc.py.
run: pytest tests/test_t08_eval_qc.py -q.
nothing else in scope. commit straight to main per D-07.
ping me with the commit sha when green.
```
