# CONTRACT — T-05 word-level karaoke subtitle renderer

**Spec ID:** T-05-word-karaoke
**Implementer:** subtitler
**Project:** /Users/jperr/Documents/shorts
**Surface:** subtitles (pipeline_v2.py — write_ass_word, align_words, render_one dispatch)
**Commit policy:** straight to main per D-07
**Independence:** runs in parallel with T-04 (different surface)

---

## Spec restatement (falsifiable)

Add a CLI flag `--subs-mode={line,word}` to `pipeline_v2.py`, defaulting to `line`.
Behavior:

1. **Line mode (default)** is byte-stable with current `write_ass`. No regression on
   existing v2 burns. Proven via golden snapshot of `write_ass(...)` for a fixed input.
2. **Word mode** runs a whisperX phoneme-alignment pass over the mlx-whisper line-level
   transcript to recover per-word timestamps, then emits an ASS dialogue line per
   utterance with `{\kNN}` karaoke tags per word (NN = word duration in centiseconds).
   The burn goes through libass like the existing line burn (`-vf "ass=..."`).
3. **Style locked:** the `Style: Default,Helvetica,72,...,544,1` line in `ASS_HEADER`
   stays exactly as it is today (Helvetica, 72pt, MarginV=544). Word mode reuses it.
4. **Frame-level oracle (smoke):** rendering a 30s tyler1 clip with `--subs-mode=word`
   produces an mp4 plus a `<out>.words.json` sidecar. Sampling two frames straddling
   a word boundary by ±0.10s and hashing only the subtitle band (rows 1500–1700)
   must yield different hashes — proof the highlight advanced.
5. **Cross-VOD smoke:** both modes succeed on at least one clip from each of the
   three eval VODs in `source/` (`vod-tyler1-jynxzi.mp4`, `vod-medium.mp4`,
   `vod-podcast.mp4`).

## Test files

- `tests/test_t05_word_karaoke.py` — 17 tests (9 unit, 1 baseline snapshot, 7 smoke gated by `RUN_SMOKE=1`)

## Run command

```
pytest tests/test_t05_word_karaoke.py -q
```

Smoke (after whisperx is installed and a model cached):

```
RUN_SMOKE=1 pytest tests/test_t05_word_karaoke.py -q
```

## Captured red output

```
FAILED tests/test_t05_word_karaoke.py::test_subs_mode_flag_exists_in_help
FAILED tests/test_t05_word_karaoke.py::test_subs_mode_default_is_line
FAILED tests/test_t05_word_karaoke.py::test_write_ass_word_function_exists
FAILED tests/test_t05_word_karaoke.py::test_write_ass_word_emits_k_karaoke_tags
FAILED tests/test_t05_word_karaoke.py::test_write_ass_word_preserves_locked_style
FAILED tests/test_t05_word_karaoke.py::test_write_ass_word_k_durations_match_word_lengths
FAILED tests/test_t05_word_karaoke.py::test_align_words_function_exists
FAILED tests/test_t05_word_karaoke.py::test_render_one_accepts_subs_mode
FAILED tests/test_t05_word_karaoke.py::test_main_passes_subs_mode_to_render_one
9 failed, 1 passed, 7 skipped in 0.40s
```

All 9 failures are missing-symbol (`AttributeError`) or missing-source-text
(`AssertionError` on grep). None are import errors, typos, or setup faults.
Red shape correctly says "the behavior is missing." The 1 passing test
(`test_line_mode_write_ass_unchanged`) is the byte-stable snapshot of the
current `write_ass` — it must continue to pass after the implementation, locking
line-mode regression risk.

## Oracle definition

- **CLI:** `--subs-mode` flag with choices `line, word`, default `"line"`
  (verified via `--help` output and a source-text grep for the literal default).
- **Word ASS structure:** `write_ass_word(words, path)` where `words = [{start, end, word}]`.
  Output ASS contains ≥ one `\k` tag per word; the sum of `\kNN` centisecond
  values within a dialogue line approximates the line's wallclock duration in
  centiseconds (±10cs tolerance).
- **Style invariance:** Style line in word-mode ASS still matches
  `Style:\s*Default,Helvetica,72,` and contains `544` at the MarginV slot.
- **Line invariance:** golden snapshot of `write_ass([{start:0, end:1.5, text:"hello world"},...])`
  is byte-stable.
- **Alignment wrapper:** `align_words(segs, audio_path) -> list[{start,end,word}]`
  exists. Implementation should wrap whisperX (`whisperx.load_align_model` +
  `whisperx.align`) over the existing mlx-whisper line segments.
- **Render dispatch:** `render_one(...)` accepts a `subs_mode` parameter and the
  main flow threads `args.subs_mode` into both render_one call sites
  (lines 615 and 648 in current pipeline_v2.py).
- **Smoke (word):** sidecar `<out>.words.json` is written; two frames straddling
  a word boundary differ in subtitle-band pixel hash.
- **Smoke (cross-VOD):** parametrized over 3 VODs × 2 modes = 6 cases, each
  produces an mp4 > 100KB.

## Out of scope

- Hook scoring / composite ranker (that is T-04, separate contract).
- Reframing logic (face/screen detection, L1 solver, TV smoothing) — do not touch.
- Changing the locked style (Helvetica 72pt MarginV=544). Adjusting font, size,
  position, or color is **explicitly forbidden** by this contract.
- Switching transcription away from mlx-whisper. Word alignment is **additive**
  on top of the existing line transcription, not a replacement.
- Adding new global dependencies beyond `whisperx` and its required pins.

## Implementation notes

- whisperX install: `pip install whisperx` (pulls torch, faster-whisper alignment
  models). The alignment-only path is documented in the whisperX README under
  "Forced Alignment". Model: `WAV2VEC2_ASR_BASE_960H` for English suffices.
- Wrap behind try/except like the existing `transcribe()` does for mlx_whisper —
  if whisperx unavailable in word mode, raise a clear error rather than silently
  falling back to line mode.
- The words sidecar (`<out>.words.json`) is required for the smoke oracle to know
  where word boundaries land; emit it next to the mp4 in the output dir.
- ASS `\kNN` value is the **karaoke duration in centiseconds** for the *next*
  word (e.g. `{\k25}wait {\k30}what` means "wait" highlighted for 250ms,
  then "what" for 300ms).
- `MarginV` in the `Style:` line is the second-to-last numeric field before
  `Encoding`; the existing v2 value is `544`. Do not change.

## Transcript

`.brutus/T-05-word-karaoke/transcript.md` — re-executable via `uvx showboat verify`.

## Handoff

subtitler: contract above. green these 9 unit tests in
`tests/test_t05_word_karaoke.py`. run: `pytest tests/test_t05_word_karaoke.py -q`.
The 7 smoke tests are your own verify gate — run them with `RUN_SMOKE=1` before
declaring done. Nothing else in scope. Commit straight to main per D-07.
T-04 is in flight on a different surface (ranker), no merge conflict expected.
