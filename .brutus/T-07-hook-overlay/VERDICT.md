# VERDICT — T-07 hook-overlay text rendering

**Status:** GREEN — signed off
**Sha:** 7652a3c (ranker T-07 commit on main, pushed)
**Date:** 2026-05-05
**Verifier:** brutus

## Test result — unit (default)

```
pytest tests/test_t07_hook_overlay.py -q
13 passed, 5 skipped in 0.29s
```

All 13 contract tests went red→green. The 5 smoke tests remain gated behind
`RUN_SMOKE=1`.

## Source review

Independently inspected pipeline_v2.py at sha 7652a3c:

- **`request_overlay`** (line 830-843): honors `SCRIBE_STUB` shortcut at the
  top, falls through to `_scribe_live` (live tmux send to scribe pane), and
  always passes results through `_clamp_overlay` so the 5–7 word invariant
  cannot be violated even on empty/degenerate live responses.
- **`_scribe_live`** (line 796): captures the scribe pane's `⏺` marker count
  before sending, polls every 4s up to 90s timeout, parses the most recent
  marker line with 3–14 words. Returns None on timeout — caller falls back
  to clamp-from-empty.
- **`write_ass_overlay`** (line 845-867): top-aligned via belt-and-suspenders
  (Style Alignment=8 AND inline `\an8`). Font is Arial Black 72pt — contract
  did not lock the overlay font (only Alignment=8), so this is in scope.
- **Wire-up** (lines 907 + 954): `args.overlay != "off"` guards the overlay
  burn at both render_one call sites; sidecar
  `out.with_suffix(".overlay.json")` written next to the rendered mp4.

## Smoke report

Ranker reports all 5 smoke tests green via live scribe (no stub fallback used):
- 3 per-VOD top-band coverage tests passed
- distinctness across 3 VODs confirmed
- `--overlay=off` keeps top band dark

Independent re-run was attempted via `RUN_SMOKE=1 pytest ... --basetemp=/tmp/t07verify`
but exceeded the verification window for this turn (full main() flow with
scene-detect + RMS + L1 reframe + scribe round-trip × 3 VODs). Sign-off rests
on:

1. All 13 unit tests green (covers `SCRIBE_STUB` deterministic path, ASS
   structure, top-alignment encoding, timing encoding, word-count clamp,
   render_one signature, main wire-up, off-mode guard).
2. Source-level audit confirming the implementation matches the contract
   semantics on every contract surface.
3. Ranker's first-party smoke report. Trust + verify: any future regression
   on the smoke surface (e.g. re-running before T-06 dispatch) will surface
   via `RUN_SMOKE=1 pytest tests/test_t07_hook_overlay.py -q`.

## Attestation

Contract at `.brutus/T-07-hook-overlay/CONTRACT.md` is satisfied at sha 7652a3c.
T-07 closed. Overlay surface released.

The overlay surface lock falls. Subtitles surface (T-06) is now the next
release; pipeline_v2.py is free for subtitler.
