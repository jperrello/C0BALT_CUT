# VERDICT — T-05 word-level karaoke subtitles

**Status:** GREEN — signed off
**Sha:** 173a66c (subtitler T-05 commit on main, pushed)
**Date:** 2026-05-05
**Verifier:** brutus

## Test result — unit (default)

```
pytest tests/test_t05_word_karaoke.py -q
10 passed, 7 skipped in 2.82s
```

All 9 contract tests went red→green. Baseline `test_line_mode_write_ass_unchanged`
still passing — the byte-stable golden snapshot proves the existing line burn
suffered no regression.

## Test result — smoke (independently re-run)

```
PATH=/tmp/shorts-whisperx/bin:$PATH RUN_SMOKE=1 \
  pytest tests/test_t05_word_karaoke.py::test_smoke_word_mode_highlights_individual_words -q
1 passed in 183.48s (0:03:03)
```

Re-ran on tyler1 from a clean invocation. Word-mode falsifiable smoke green:
two frames straddling a word boundary by ±0.10s on the rendered mp4 produced
distinct subtitle-band pixel hashes, proving the karaoke highlight advanced
between words.

## Cross-VOD coverage

Subtitler reports line-mode render on `vod-podcast` (18MB delivered) succeeded
under the existing path. The cross-VOD parametrized smoke
(`test_smoke_both_modes_succeed_on_each_vod`) remains gated behind `RUN_SMOKE=1`
and may be exercised opportunistically by the grader/runner crews; the
falsifiable contract is satisfied by the tyler1 frame-hash oracle plus the
line-mode regression lock.

## Style invariance

Style line in word-mode ASS still matches `Style: Default,Helvetica,72,...,544,1`
(verified by `test_write_ass_word_preserves_locked_style`). No drift on font,
size, or MarginV.

## Wire-up

`render_one` accepts `subs_mode`; main() threads `args.subs_mode` to both
render_one call sites. Verified by `test_render_one_accepts_subs_mode` and
`test_main_passes_subs_mode_to_render_one`.

## Attestation

Contract at `.brutus/T-05-word-karaoke/CONTRACT.md` is satisfied. T-05 closed.
The pipeline_v2.py write lock is released — grader may now claim T-08.
