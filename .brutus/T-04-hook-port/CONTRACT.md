# CONTRACT — T-04 hook scorer port + composite ranker

**Spec ID:** T-04-hook-port
**Implementer:** ranker
**Project:** /Users/jperr/Documents/shorts
**Surface:** ranker (pipeline_v2.py)
**Commit policy:** straight to main per D-07

---

## Spec restatement (falsifiable)

Port v1's hook-scoring two-pass ranker into `pipeline_v2.py`, replacing the current
energy-only path. After the port:

1. `pipeline_v2.HOOK_WORDS` (already present) and `pipeline_v2.hook_score(segs, rms_clip, start_abs)`
   exist as importable symbols. `hook_score` must score a first-3s segment containing
   any HOOK_WORDS interjection (e.g. "wait", "bro", "yo") strictly higher than neutral text,
   contributing at least +1.0 for a hook-word match.
2. A `pipeline_v2.composite_score(cand) -> float` function exists and equals
   `cand["score"] + alpha * cand["hook_score"]` for some alpha in (0, 10]. Two candidates
   with equal base score but different hook_score must rank in hook_score order.
3. A `pipeline_v2.score_features(segs, rms_clip, cs, ce) -> dict` returns a dict with
   keys `hook_in_first_3s` (bool), `standalone_3s` (bool), `duration_fit` (float).
   `hook_in_first_3s` is True iff a HOOK_WORDS token appears in segments with
   `start < 3.0`. `duration_fit` is maximized at the v2 target window of ~45s and
   degrades for shorter/longer windows.
4. A `pipeline_v2.pick_variety(cands, n, min_gap=600.0)` function exists with
   `min_gap` defaulting to **600.0 seconds** (10 minutes), and never selects two
   candidates whose `start` values are within `min_gap` of each other.
5. `pipeline_v2`'s `main()` flow must use the composite/variety pipeline. The
   exact legacy line `final = pick(cands, n=args.n)` must be removed. The main
   flow must reference `hook_score` and either `composite_score` or `pick_variety`.
6. **End-to-end smoke oracle** (gated behind `RUN_SMOKE=1`, skipped in CI by default):
   running `python3 pipeline_v2.py source/vod-tyler1-jynxzi.mp4 <outdir> --n 2`
   produces `<outdir>/shorts.json` where (a) the first 3s of `shorts[0].transcript`
   contains a HOOK_WORDS token, and (b) `shorts[0].source_start` and
   `shorts[1].source_start` differ by ≥ 600.0 seconds.

## Test files

- `tests/test_t04_hook_port.py` — 18 tests (16 must turn green, 1 baseline pass already, 1 smoke gated)

## Run command

```
pytest tests/test_t04_hook_port.py --no-header -q
```

For the smoke oracle (after source/vod-tyler1-jynxzi.mp4 finishes downloading):

```
RUN_SMOKE=1 pytest tests/test_t04_hook_port.py::test_smoke_tyler1_first_3s_has_hook_word -s
```

## Captured red output

```
FAILED tests/test_t04_hook_port.py::test_hook_score_callable
FAILED tests/test_t04_hook_port.py::test_hook_score_distinguishes_hook_from_neutral
FAILED tests/test_t04_hook_port.py::test_hook_score_empty_segs_zero
FAILED tests/test_t04_hook_port.py::test_composite_score_function_exists
FAILED tests/test_t04_hook_port.py::test_composite_score_promotes_hook_bearing_candidate
FAILED tests/test_t04_hook_port.py::test_composite_score_alpha_positive_and_sane
FAILED tests/test_t04_hook_port.py::test_score_features_function_exists
FAILED tests/test_t04_hook_port.py::test_score_features_keys_present
FAILED tests/test_t04_hook_port.py::test_hook_in_first_3s_true_when_hook_word_in_head
FAILED tests/test_t04_hook_port.py::test_hook_in_first_3s_false_when_hook_word_after_3s
FAILED tests/test_t04_hook_port.py::test_duration_fit_peaks_near_45s
FAILED tests/test_t04_hook_port.py::test_pick_variety_function_exists
FAILED tests/test_t04_hook_port.py::test_pick_variety_enforces_10min_gap
FAILED tests/test_t04_hook_port.py::test_pick_variety_default_min_gap_is_600
FAILED tests/test_t04_hook_port.py::test_legacy_energy_only_pick_removed_from_main
FAILED tests/test_t04_hook_port.py::test_main_flow_invokes_hook_rescore
16 failed, 1 passed, 1 skipped in 0.16s
```

All 16 failures are `AttributeError` on missing functions or `AssertionError` on
missing source-text wire-up. None are import errors, typos, or setup faults — the
red shape correctly says "the behavior is missing."

## Oracle definition

- **Hook signal correctness:** `hook_score(hook_segs) > hook_score(neutral_segs)` and
  hook-word presence contributes ≥ 1.0. Mirrors v1's `pipeline.py:160-172` math
  (`1.0 * hit + 0.5 * qmark + 1.0 * early_peak`).
- **Composite ranker:** `composite_score(c) = c["score"] + alpha * c["hook_score"]`,
  `0 < alpha ≤ 10`. The merge-map at `research-geoff-hookport.md:9` documents
  v1's value of `2.0`; that is in range.
- **Features:** dict keys exactly `hook_in_first_3s`, `standalone_3s`, `duration_fit`.
  Type-checked. `hook_in_first_3s` semantically tied to HOOK_WORDS in segs with start<3.0.
  `duration_fit` peaks near 45s (matches v2's existing target).
- **Variety:** `pick_variety` is a pure function: given candidates with `start` and
  `score` keys, returns ≤ n candidates with all pairwise `|start_i - start_j| ≥ min_gap`,
  greedy by descending composite. Default `min_gap=600.0`.
- **Wire-up:** source-level grep — legacy line gone, new symbols referenced. This
  catches the case where someone defines the helpers but never calls them.
- **Smoke (end-to-end):** the user-visible oracle. Top-1 short opens with a hook word;
  top-2 shorts come from different 10-minute windows of the source.

## Out of scope

- Subtitle rendering — that is T-05 (separate contract, separate implementer).
- Face/screen reframing logic in `pipeline_v2.py` — do not touch.
- The render path (`render_one`, `deliver`) — do not modify.
- The `score_scenes` base scorer (`pipeline_v2.py:496-511`) — leave intact.
- `pipeline.py` (v1) — do not edit; this is a port FROM, not a rewrite of.
- Adding new dependencies. The port needs only what v1 used: numpy, mlx_whisper, stdlib.

## Implementation notes (from research-geoff-hookport.md)

- Insertion point: `pipeline_v2.py:574-579` — replace `final = pick(cands, n=args.n)`
  with v1's two-pass `shortlist → transcribe → rescore → pick_variety` chain
  (`pipeline.py:341-354`).
- Per-clip RMS slice mirrors v1: `clip_rms = rms[a:b] if b > a else np.array([0.0])`.
- Write `c["hook_score"]` and `c["segs"]` onto candidates so the render pass can
  reuse `segs` later.
- Extend the result-meta dict at `pipeline_v2.py:587+` with `hook_score` and a
  `transcript` array (needed for the smoke oracle to introspect first-3s text).

## Transcript

`.brutus/T-04-hook-port/transcript.md` — re-executable via `uvx showboat verify`.

## Handoff

ranker: contract above. green these 16 tests. run: `pytest tests/test_t04_hook_port.py -q`.
nothing else in scope. commit straight to main per D-07. when green, ping me with
the commit sha so i can re-run and write VERDICT.md.
