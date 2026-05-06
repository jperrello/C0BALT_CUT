# CONTRACT — T-09 A/B variant trim emitter

**Spec ID:** T-09-ab-variants
**Implementer:** ranker
**Project:** /Users/jperr/Documents/shorts
**Surface:** ranker (pipeline_v2.py — variant_windows + render-loop fan-out)
**Commit policy:** straight to main per D-07
**Status:** **PRE-STAGED — DO NOT HAND OFF YET.** Release after subtitler T-06 commits to main, to avoid pipeline_v2.py merge conflict.

---

## Spec restatement (falsifiable)

For each shortlisted top-N moment, emit **two** variant clips whose payoffs
land at the same absolute timestamp but whose lead windows differ by 5 seconds.
Both variants are rendered, delivered, and graded independently — both land
in `delivered/` if they pass eval.

### Required public API

- `pipeline_v2.variant_windows(clip_start, clip_end, payoff_abs) -> list[tuple]` —
  pure function returning **exactly two** `(cs, ce)` pairs. Invariants:
  - the two `cs` values differ by exactly 5.0s (the lead shift),
  - both `[cs, ce]` windows contain `payoff_abs`,
  - both window durations satisfy `25.0 ≤ ce - cs ≤ 65.0` (v2 duration band).

### Render loop changes (pipeline_v2.py:951+)

For each `c` in `final`, iterate the two variant windows. For variant index
`v ∈ ["a", "b"]`:

- output stem: `short-{i:02d}-{v}.mp4` (downstream `deliver()` produces
  `<bead>-<ts>-short-NN-{a,b}.mp4` via the existing stem propagation),
- `render_one(...)` per variant,
- `deliver(out)` per variant (which already chains `grade()`),
- meta entry per variant including `variant: "a" | "b"` and
  `payoff_abs: float`.

### Shorts.json schema

Each meta entry must include the existing fields PLUS:
- `variant`: `"a"` or `"b"`
- `payoff_abs`: absolute timestamp of the moment's payoff in source seconds

These let downstream tooling correlate variant pairs and verify alignment
without re-deriving payoff from RMS.

## Test files

- `tests/test_t09_ab_variants.py` — 13 tests (11 unit, 2 smoke gated by `RUN_SMOKE=1`)

## Run command

```
pytest tests/test_t09_ab_variants.py -q
```

Smoke (after T-06 lands):

```
RUN_SMOKE=1 pytest tests/test_t09_ab_variants.py -q
```

## Captured red output

```
FAILED tests/test_t09_ab_variants.py::test_variant_windows_function_exists
FAILED tests/test_t09_ab_variants.py::test_variant_windows_returns_two_pairs
FAILED tests/test_t09_ab_variants.py::test_variant_windows_lead_differs_by_5s
FAILED tests/test_t09_ab_variants.py::test_variant_windows_payoff_preserved
FAILED tests/test_t09_ab_variants.py::test_variant_windows_lengths_in_band
FAILED tests/test_t09_ab_variants.py::test_variant_windows_distinct_starts
FAILED tests/test_t09_ab_variants.py::test_main_uses_variant_windows
FAILED tests/test_t09_ab_variants.py::test_naming_pattern_a_b_suffix
FAILED tests/test_t09_ab_variants.py::test_each_variant_calls_deliver_and_grade
FAILED tests/test_t09_ab_variants.py::test_shorts_json_meta_includes_payoff_abs
FAILED tests/test_t09_ab_variants.py::test_shorts_json_meta_includes_variant_label
11 failed, 2 skipped in 0.25s
```

All 11 failures are missing-symbol or missing-source-text. None are import
errors, typos, or setup faults. Red shape correctly says "the behavior is missing."

## Oracle definition

- **`variant_windows` shape:** returns exactly 2 (cs, ce) tuples, lead shift
  exactly 5.0s, both windows contain payoff, both durations in [25, 65],
  the two pairs are distinct.
- **Render loop fan-out:** source-grep verifies `variant_windows` is called
  in the render path; `-a` / `-b` literals appear in the naming logic;
  `deliver(` is called per variant (≥2 calls in the render-loop region OR
  inside an inner per-variant loop with ≥1 call).
- **Schema additions:** `payoff_abs` and `'variant'` (or `"variant"`) appear
  in the source.
- **Smoke pair:** `--n=1` produces exactly 2 entries in `shorts.json` with
  labels `["a", "b"]`, both files on disk, both filenames match the
  `-a.mp4` / `-b.mp4` pattern.
- **Smoke alignment:** `payoff_abs` of the two variants agree within 0.5s;
  `source_start` values differ by >1s (proving they are genuinely distinct
  trims, not duplicates).

## Out of scope

- Subtitle / overlay rendering — both flow through unchanged for each variant.
- Hook scoring or composite ranker (T-04, shipped).
- Eval/QC grader (T-08, shipped). The grader runs per variant, automatically
  via the existing `deliver() → grade()` chain. No grader edits required.
- Variant counts other than 2. The spec locks at 2; do NOT add `--variants=N`.
- A/B winner selection / engagement tracking — that is downstream tooling,
  out of T-09.
- Adding new dependencies.

## Implementation notes

- `payoff_abs` derivation: existing v2 has `find_payoff` semantics inside
  `shape_window` (max RMS index). Re-derive once per shortlisted candidate
  using `audio_rms` slice → `argmax`, store on `c["payoff_abs"]` before the
  variant loop.
- `variant_windows` lead shift: easiest correct shape is to anchor variant
  A at `(payoff_abs - lead_a, payoff_abs - lead_a + dur)` and variant B at
  `(payoff_abs - (lead_a + 5.0), payoff_abs - (lead_a + 5.0) + dur)`. Then
  both contain payoff (assuming `dur > 5 + lead_a`) and `cs` values differ
  by 5.0s.
- Be careful not to walk past source bounds: clamp at 0 and source duration;
  if clamping forces both variants to the same window, raise — do NOT
  silently emit duplicates (the `test_variant_windows_distinct_starts` will
  catch it).
- `deliver()` already sources its filename suffix from `out.stem`, so
  passing `short-01-a.mp4` / `short-01-b.mp4` is enough — no `deliver()`
  edits needed.

## Cross-spec coordination

- **Doubles render time per shortlist** — T-09 emits 2× the existing render
  count. This compounds with the OOM history; runner/overseer should plan
  for serialized variant rendering rather than parallel.
- **Eval loop already covers it** — both variants flow through `deliver()`
  → `grade()` automatically; no T-08 changes needed. Rejection routing
  (`delivered/rejected/<reason>/`) handles per-variant rejects.

## Transcript

`.brutus/T-09-ab-variants/transcript.md` — re-executable via `uvx showboat verify`.

## Handoff

**HOLD.** Do not dispatch to ranker until parent confirms subtitler T-06 has
committed to main. When released:

```
brutus contract at /Users/jperr/Documents/shorts/.brutus/T-09-ab-variants/CONTRACT.md.
green these 11 unit tests in tests/test_t09_ab_variants.py.
run: pytest tests/test_t09_ab_variants.py -q.
2 smoke tests are your verify gate — run with RUN_SMOKE=1 before declaring done.
nothing else in scope. commit straight to main per D-07.
ping me with the commit sha when green.
```
