# CONTRACT — T-07 hook-overlay text rendering

**Spec ID:** T-07-hook-overlay
**Implementer:** ranker (with scribe as service)
**Project:** /Users/jperr/Documents/shorts
**Surface:** overlay (pipeline_v2.py — request_overlay, write_ass_overlay, render_one dispatch)
**Commit policy:** straight to main per D-07
**Status:** **PRE-STAGED — DO NOT HAND OFF YET.** Release after grader's T-08 commits to main, to avoid pipeline_v2.py merge conflict.

---

## Spec restatement (falsifiable)

Add a CLI flag `--overlay={off,on}` to `pipeline_v2.py`, default `on`. For each
shortlisted clip, the ranker pipeline calls `scribe` (service crew, via tmux
send) to obtain a 5–7 word TikTok-grammar hook line, then renders it as a
top-of-frame ASS title (Alignment=8 / `\an8`) burned alongside the existing
subtitle layer.

### Test seam (mandatory)

`request_overlay` must honor an env var `SCRIBE_STUB`: when set, return its value
verbatim (after the 5–7 word clamp). This lets tests drive deterministic
overlay text without spinning up the live scribe pane. The tmux-backed live path
is exercised only under `RUN_SMOKE=1`.

### Required public API

- `pipeline_v2.request_overlay(transcript: str, features: dict) -> str` —
  returns a 5–7 word string. Always clamps; never returns >7 or <5.
- `pipeline_v2.write_ass_overlay(text: str, start: float, end: float, path: Path)` —
  emits ASS with the overlay text burned at the top of the canvas (Alignment=8
  in the Style section or an inline `{\an8}` override on the dialogue line).
- `pipeline_v2.render_one(...)` — accepts an `overlay` parameter (overlay text
  string, or None / "off" to skip).
- `main()` — wires `--overlay=on/off`, calls `request_overlay` per shortlisted
  clip with the clip's transcript snippet + score_features dict, threads the
  overlay text into `render_one`. When `--overlay=off`, no scribe call and no
  overlay burn.

### Falsifiable smoke (3 eval VODs)

- Each of `vod-tyler1-jynxzi.mp4`, `vod-medium.mp4`, `vod-podcast.mp4` rendered
  with `--overlay=on` produces an mp4 plus a `<stem>.overlay.json` sidecar.
- Top band (rows 0–200) of the rendered mp4 at t=1.5s has > 0.5% bright pixels
  (luma > 200) — proxy for "overlay text is rendered".
- The three overlays are distinct strings.
- `--overlay=off` on the same input yields a top band with < 0.5% bright pixels.

## Test files

- `tests/test_t07_hook_overlay.py` — 18 tests (13 unit + 5 smoke gated by `RUN_SMOKE=1`)

## Run command

```
pytest tests/test_t07_hook_overlay.py -q
```

Smoke (after grader T-08 lands):

```
RUN_SMOKE=1 pytest tests/test_t07_hook_overlay.py -q
```

## Captured red output

```
FAILED tests/test_t07_hook_overlay.py::test_overlay_flag_in_help
FAILED tests/test_t07_hook_overlay.py::test_overlay_default_is_on
FAILED tests/test_t07_hook_overlay.py::test_request_overlay_function_exists
FAILED tests/test_t07_hook_overlay.py::test_request_overlay_signature_takes_transcript_and_features
FAILED tests/test_t07_hook_overlay.py::test_request_overlay_returns_5_to_7_words
FAILED tests/test_t07_hook_overlay.py::test_request_overlay_truncates_or_rejects_overlong_stub
FAILED tests/test_t07_hook_overlay.py::test_write_ass_overlay_function_exists
FAILED tests/test_t07_hook_overlay.py::test_write_ass_overlay_top_aligned
FAILED tests/test_t07_hook_overlay.py::test_write_ass_overlay_includes_timing
FAILED tests/test_t07_hook_overlay.py::test_render_one_accepts_overlay_param
FAILED tests/test_t07_hook_overlay.py::test_main_threads_overlay_flag
FAILED tests/test_t07_hook_overlay.py::test_overlay_off_disables_burn
FAILED tests/test_t07_hook_overlay.py::test_ranker_invokes_request_overlay
13 failed, 5 skipped in 0.21s
```

All 13 failures are missing-symbol (`AttributeError`) or missing-source-text
(`AssertionError` on grep). None are import errors, typos, or setup faults.
Red shape correctly says "the behavior is missing."

## Oracle definition

- **CLI:** `--overlay` flag with choices `on, off`, default `"on"` literal.
- **Word-count clamp:** `request_overlay` always returns 5–7 words, even when
  `SCRIBE_STUB` is overlong. Tested with both an in-range stub (6 words) and
  an overlong stub (12 words).
- **Top alignment:** `write_ass_overlay` output contains `\an8` OR a Style line
  with Alignment=8. Either is acceptable; both render at top-center.
- **Timing:** ASS dialogue uses the supplied `start`/`end` (verified via
  literal `0:00:01.50` / `0:00:07.00` substring match).
- **Wire-up:** source-grep verifies `args.overlay`, `request_overlay(`,
  `render_one(...overlay...)`, and a guard around `overlay=='off'` /
  `overlay!='off'` / `if overlay:`.
- **Smoke (per-VOD):** mp4 produced; sidecar `<stem>.overlay.json` carries
  `{"text": "..."}`; top-band bright-pixel coverage > 0.5%.
- **Smoke (distinctness):** three sidecar texts form a 3-element set (no
  duplicates) — proves scribe adapted per clip.
- **Smoke (off-mode):** `--overlay=off` keeps top-band coverage < 0.5%.

## Out of scope

- Subtitle rendering (line/word) — that is T-05, already shipped. Do not edit
  `write_ass`, `write_ass_word`, `align_words`, or the libass burn for subs.
- Hook scorer / composite ranker — that is T-04, already shipped.
- Eval/QC grader — that is T-08, in flight on a different surface.
- Reframing logic — do not touch `compute_reframe_signal`, L1/TV smoothers,
  face detection.
- Locking the overlay font/size/color/MarginV. Pick reasonable defaults; the
  contract only locks Alignment=8 (top center). Future T- specs may tighten.
- Scribe's prompt engineering — out of brutus scope. The contract only requires
  that scribe is consulted (via tmux send) and returns a 5–7 word string;
  whatever prompt the implementer feeds scribe is their call.

## Implementation notes

- Test seam first: implement the `SCRIBE_STUB` shortcut at the top of
  `request_overlay` before wiring tmux. This unblocks the entire unit suite
  without requiring a live scribe pane.
- Live path: `bash ~/.claude/skills/crew/crew.sh send scribe "<prompt>"`,
  then poll the scribe pane's tmux capture for the response. Cap the wait
  with a generous timeout; on timeout, fall back to a deterministic stub
  derived from the transcript head (do not crash the render).
- Overlay timing: render the overlay across the full clip duration (0..ce-cs).
  No per-word timing required — single dialogue line is fine.
- Burn order: chain ASS filters for both the subtitle and the overlay, e.g.
  `-vf "ass=clip.ass,ass=overlay.ass"`. The two ASS files have non-overlapping
  Alignment regions (subs MarginV=544 bottom, overlay top) so they coexist.
- Sidecar (`<stem>.overlay.json`) is required for the smoke distinctness
  oracle. Format: `{"text": "...", "source_start": float, "source_end": float}`.

## Transcript

`.brutus/T-07-hook-overlay/transcript.md` — re-executable via `uvx showboat verify`.

## Handoff

**HOLD.** Do not dispatch to ranker until parent confirms grader T-08 has
committed to main. When released:

```
brutus contract at /Users/jperr/Documents/shorts/.brutus/T-07-hook-overlay/CONTRACT.md.
green these 13 unit tests in tests/test_t07_hook_overlay.py.
run: pytest tests/test_t07_hook_overlay.py -q.
5 smoke tests are your verify gate — run with RUN_SMOKE=1 before declaring done.
nothing else in scope. commit straight to main per D-07.
ping me with the commit sha when green.
```
