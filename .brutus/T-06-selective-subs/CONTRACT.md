# CONTRACT — T-06 selective subtitles (engagement-judge-gated)

**Spec ID:** T-06-selective-subs
**Implementer:** subtitler (with judge as service)
**Project:** /Users/jperr/Documents/shorts
**Surface:** subtitles (pipeline_v2.py — tag_candidate_spans, judge_span, select_engaging_spans, write_ass_selective, render_one dispatch)
**Commit policy:** straight to main per D-07
**Status:** **PRE-STAGED — DO NOT HAND OFF YET.** Release after ranker T-07 commits to main, to avoid pipeline_v2.py merge conflict.

---

## Spec restatement (falsifiable)

Add a third subtitle mode `selective` to `pipeline_v2.py`. **Default flips from
`line` (T-05) to `selective`.** In selective mode, the pipeline burns ASS
dialogue **only** for transcript segments that overlap an "engaging" span.

### Engagement detection (two-stage)

**Stage 1 — local-signal tagger.** A candidate span fires when ANY of:
- RMS z-score > 1.5 at some second-aligned index inside `[cs, ce]` (reason: `rms_peak`)
- A transcript segment's text contains a `HOOK_WORDS` interjection (reason: `hook_word`)
- A scene cut lands inside `[cs, ce]` (reason: `scene_cut`); the candidate
  span is roughly `[cut-1s, cut+1s]`.

**Stage 2 — judge gate.** Each candidate is sent via tmux to the `judge`
service crew with the span's transcript text + features. Judge returns
`Y`/`N`. Only `Y` spans get `engaging=True`.

### Test seam (mandatory)

`judge_span` must honor an env var `JUDGE_STUB`:
- `JUDGE_STUB=Y` → returns True
- `JUDGE_STUB=N` → returns False
- `JUDGE_STUB=Y,N,Y` → consumed in order across calls

Implementer must implement the stub-shortcut at the top of `judge_span` before
wiring tmux. This unblocks the entire unit suite without a live judge pane.

### Required public API

- `pipeline_v2.tag_candidate_spans(segs, rms, scene_cuts, cs, ce) -> list[dict]` —
  pure function. Each dict: `{start, end, reason}` where reason is one of
  `rms_peak`, `hook_word`, `scene_cut`.
- `pipeline_v2.judge_span(text: str, features: dict) -> bool` — judge wrapper.
- `pipeline_v2.select_engaging_spans(segs, rms, scene_cuts, cs, ce) -> list[dict]` —
  combines stages. Each dict: `{start, end, engaging: bool, reason: str}`.
- `pipeline_v2.write_ass_selective(segs, engaging_spans, path)` — emits ASS
  with dialogue ONLY for `segs` whose `[start, end]` overlaps any
  `engaging=True` span.
- `render_one` dispatches on `subs_mode == "selective"` and calls the chain.
- `main` threads `args.subs_mode` and writes a `<stem>.subtitle_spans.json`
  sidecar containing the full span list (engaging + vetoed) for the smoke oracle.

### Locked invariants from prior contracts

- Style line stays Helvetica 72pt MarginV=544 (T-05 lock — verified by
  `test_write_ass_selective_preserves_locked_style`).
- `--subs-mode=line` and `--subs-mode=word` continue to work unchanged.

## Test files

- `tests/test_t06_selective_subs.py` — 21 tests (19 unit, 2 smoke gated by `RUN_SMOKE=1`)

## Run command

```
pytest tests/test_t06_selective_subs.py -q
```

Smoke (after T-07 lands and judge is available):

```
RUN_SMOKE=1 pytest tests/test_t06_selective_subs.py -q
```

## Captured red output

```
FAILED tests/test_t06_selective_subs.py::test_subs_mode_default_is_selective
FAILED tests/test_t06_selective_subs.py::test_subs_mode_choices_include_selective
FAILED tests/test_t06_selective_subs.py::test_tag_candidate_spans_function_exists
FAILED tests/test_t06_selective_subs.py::test_tag_fires_on_rms_peak
FAILED tests/test_t06_selective_subs.py::test_tag_fires_on_hook_word
FAILED tests/test_t06_selective_subs.py::test_tag_fires_on_scene_cut
FAILED tests/test_t06_selective_subs.py::test_tag_returns_empty_when_no_signal
FAILED tests/test_t06_selective_subs.py::test_judge_span_function_exists
FAILED tests/test_t06_selective_subs.py::test_judge_span_honors_stub_yes
FAILED tests/test_t06_selective_subs.py::test_judge_span_honors_stub_no
FAILED tests/test_t06_selective_subs.py::test_judge_span_consumes_sequence
FAILED tests/test_t06_selective_subs.py::test_select_engaging_spans_function_exists
FAILED tests/test_t06_selective_subs.py::test_select_engaging_spans_filters_by_judge
FAILED tests/test_t06_selective_subs.py::test_write_ass_selective_function_exists
FAILED tests/test_t06_selective_subs.py::test_write_ass_selective_skips_non_engaging
FAILED tests/test_t06_selective_subs.py::test_write_ass_selective_no_engaging_means_no_dialogue
FAILED tests/test_t06_selective_subs.py::test_write_ass_selective_preserves_locked_style
FAILED tests/test_t06_selective_subs.py::test_main_threads_selective_mode
FAILED tests/test_t06_selective_subs.py::test_render_one_dispatches_on_selective
19 failed, 2 skipped in 0.27s
```

All 19 failures are missing-symbol or missing-source-text. None are import
errors, typos, or setup faults. Red shape correctly says "the behavior is missing."

## Oracle definition

- **Tagger semantics** locked at the unit level: each of the three signal
  sources is tested in isolation; flat audio + neutral text + no cuts must
  produce zero candidates (no false positives).
- **Scene-cut window** locked at ≤ ±1s.
- **Judge stub** is the contract surface for unit tests; implementer cannot
  refactor it away — `JUDGE_STUB=Y/N` and `JUDGE_STUB=Y,N,Y` sequences must
  both work.
- **Selective burn** semantics:
  - segs overlapping an engaging span → present in ASS dialogue
  - segs entirely outside → absent
  - empty engaging spans list → no `Dialogue:` lines at all (header only)
- **Style invariance:** Helvetica 72pt MarginV=544 — same lock as T-05.
- **Smoke (podcast):** sidecar `<stem>.subtitle_spans.json` reveals
  - ≥1 engaging span fires
  - engaging coverage < 85% of clip duration (visible non-subtitled stretches)
  - every engaging span's reason ∈ `{rms_peak, hook_word, scene_cut, judge}`
- **Smoke (line mode regression):** explicit `--subs-mode=line` does NOT inherit
  selective filtering.

## Out of scope

- Modifying the line-mode or word-mode burn paths (T-05 territory). Those
  remain byte-stable.
- Hook scoring / composite ranker (T-04, shipped).
- Eval/QC grader (T-08, shipped).
- Hook overlay (T-07, in flight on a different surface).
- Reframing logic.
- Tuning judge prompts — the contract only specifies the Y/N protocol and the
  tmux send mechanism. Implementer chooses what to feed judge.
- Adding new dependencies. The tagger needs only numpy + the existing
  HOOK_WORDS / scene_cuts / rms structures already in pipeline_v2.

## Implementation notes

- `tag_candidate_spans` is pure — easy to unit test, no I/O. Implement first,
  green its tests, then build outward.
- `judge_span` stub-first: top of function, `if (s := os.environ.get("JUDGE_STUB"))`,
  pop one comma-separated token per call (use a module-level cursor). Wire tmux
  only after stub tests are green.
- Live judge path: `bash ~/.claude/skills/crew/crew.sh send judge "<prompt>"`,
  poll judge pane via tmux capture for `Y` or `N`. On timeout, default to N
  (conservative — drop ambiguous spans rather than burn noise).
- `select_engaging_spans` returns BOTH engaging and vetoed spans (with
  `engaging` flag) so the sidecar can show what was considered + filtered.
- `write_ass_selective`: re-use `ASS_HEADER`. For each seg, compute overlap
  with each engaging span; if any overlap > 0, emit the Dialogue line as in
  the existing `write_ass`.
- Sidecar emission belongs in main/render_one, not in `write_ass_selective`.
  Path: `<output_stem>.subtitle_spans.json` next to the mp4 in the outdir.
- **Default flip** is a real semantic change. Make sure --subs-mode without
  an explicit value selects selective mode (and the existing default-line
  test in T-05's suite has been retired or updated).

## Cross-spec coordination

- T-05 has a test that asserts `--subs-mode` default is `line`. After T-06
  flips the default, that T-05 test must be UPDATED (not deleted) to assert
  `selective` — the line-mode WRITER behavior is what the T-05 contract
  locks, not the default. Implementer should grep T-05 tests for the
  default-mode assertion and adjust the literal.

## Transcript

`.brutus/T-06-selective-subs/transcript.md` — re-executable via `uvx showboat verify`.

## Handoff

**HOLD.** Do not dispatch to subtitler until parent confirms ranker T-07
has committed to main. When released:

```
brutus contract at /Users/jperr/Documents/shorts/.brutus/T-06-selective-subs/CONTRACT.md.
green these 19 unit tests in tests/test_t06_selective_subs.py.
run: pytest tests/test_t06_selective_subs.py -q.
2 smoke tests are your verify gate — run with RUN_SMOKE=1 before declaring done.
default-mode update needed in tests/test_t05_word_karaoke.py — adjust the literal,
do not delete the test. nothing else in scope. commit straight to main per D-07.
ping me with the commit sha when green.
```
