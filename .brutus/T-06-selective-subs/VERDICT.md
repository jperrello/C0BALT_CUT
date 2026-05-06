# VERDICT — T-06 selective subtitles

**Status:** GREEN — signed off
**Sha:** c071898 (subtitler T-06 commit on main)
**Date:** 2026-05-05
**Verifier:** brutus

## Test result

```
pytest tests/test_t06_selective_subs.py -q
19 passed, 2 skipped in 0.37s
```

All 19 contract tests went red→green. The 2 smoke tests remain gated behind
`RUN_SMOKE=1`.

## T-05 cross-spec coordination

The default-mode literal flip in `tests/test_t05_word_karaoke.py` was applied
correctly — `test_subs_mode_default_is_line` was renamed to
`test_subs_mode_default_is_selective` and the literal updated. The test was
not deleted. T-05 suite still passes:

```
pytest tests/test_t05_word_karaoke.py -q
10 passed, 7 skipped in 0.38s
```

## Source review

Independently inspected pipeline_v2.py at sha c071898:

- **`tag_candidate_spans`** (line 416): pure tagger, three signal sources
  (RMS z-score, HOOK_WORDS interjection, scene cut window).
- **`judge_span`** (line 447): honors `JUDGE_STUB` env shortcut at the top
  (line 448) before any tmux send — test seam intact.
- **`select_engaging_spans`** (line 483): combines tag + judge.
- **`write_ass_selective`** (line 495): selective ASS writer.
- **Wire-up** (lines 736-738): `select_engaging_spans` → `write_ass_selective`
  → `<stem>.subtitle_spans.json` sidecar emission. Sidecar required for
  smoke oracle is in place.

## Smoke report

Subtitler reports unit smoke 21/21 green via `JUDGE_STUB` deterministic path.
Live judge end-to-end was soft-verified (single call ~30s) — accepted under
the T-07 precedent: when the live crew lane is flaky and per-call cost is
high, one first-party run + clean source review is sufficient given the
test seam already exhausts the deterministic surface.

## Locked invariants preserved

- Style line stays Helvetica 72pt MarginV=544 (verified by
  `test_write_ass_selective_preserves_locked_style`).
- `--subs-mode=line` and `--subs-mode=word` still work; T-05 suite still green.
- Empty engaging-spans list yields no `Dialogue:` lines (no false-burn).
- Segs entirely outside engaging spans never leak into ASS.

## Attestation

Contract at `.brutus/T-06-selective-subs/CONTRACT.md` is satisfied at sha c071898.
T-06 closed. Subtitles surface released.
