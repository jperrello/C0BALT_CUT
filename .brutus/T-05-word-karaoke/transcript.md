# T-05 word karaoke subs — red phase

*2026-05-05T21:31:55Z by Showboat 0.6.1*
<!-- showboat-id: 7429599e-15dc-4ae1-9689-c94cf9ca86c4 -->

Spec: --subs-mode={line,word} on pipeline_v2.py defaulting to line. Word mode runs whisperX phoneme alignment over mlx-whisper line output, emits ASS dialogue with per-word \k karaoke tags, burns via libass. Style locked: Helvetica 72pt MarginV=544. Smoke oracle: word-mode tyler1 clip → mp4 in delivered/, frame-sample at a word boundary shows the subtitle band pixel-hash differs (active highlight advanced); line mode unchanged; both modes succeed on each of three eval VODs. Tests below MUST be red — they prove the behavior is missing.

```bash
pytest tests/test_t05_word_karaoke.py --no-header -q 2>&1 | tail -25
```

```output
E       AssertionError: render_one must accept subs_mode parameter to dispatch line vs word burn
E       assert 'subs_mode' in mappingproxy(OrderedDict({'src': <Parameter "src">, 'cs': <Parameter "cs">, 'ce': <Parameter "ce">, 'out': <Parameter "out">, 'reframe_mode': <Parameter "reframe_mode='l1'">}))
E        +  where mappingproxy(OrderedDict({'src': <Parameter "src">, 'cs': <Parameter "cs">, 'ce': <Parameter "ce">, 'out': <Parameter "out">, 'reframe_mode': <Parameter "reframe_mode='l1'">})) = <Signature (src, cs, ce, out, reframe_mode='l1')>.parameters

tests/test_t05_word_karaoke.py:140: AssertionError
___________________ test_main_passes_subs_mode_to_render_one ___________________

    def test_main_passes_subs_mode_to_render_one():
        src = (ROOT / "pipeline_v2.py").read_text()
>       assert "subs_mode" in src, "subs_mode never threaded through main"
E       AssertionError: subs_mode never threaded through main
E       assert 'subs_mode' in '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport argparse\nimport json\nimport math\nimport os\ni..."shorts": meta}, indent=2))\n    print(f"[v2] wrote {len(meta)} shorts")\n\n\nif __name__ == "__main__":\n    main()\n'

tests/test_t05_word_karaoke.py:146: AssertionError
=========================== short test summary info ============================
FAILED tests/test_t05_word_karaoke.py::test_subs_mode_flag_exists_in_help - A...
FAILED tests/test_t05_word_karaoke.py::test_subs_mode_default_is_line - Asser...
FAILED tests/test_t05_word_karaoke.py::test_write_ass_word_function_exists - ...
FAILED tests/test_t05_word_karaoke.py::test_write_ass_word_emits_k_karaoke_tags
FAILED tests/test_t05_word_karaoke.py::test_write_ass_word_preserves_locked_style
FAILED tests/test_t05_word_karaoke.py::test_write_ass_word_k_durations_match_word_lengths
FAILED tests/test_t05_word_karaoke.py::test_align_words_function_exists - Ass...
FAILED tests/test_t05_word_karaoke.py::test_render_one_accepts_subs_mode - As...
FAILED tests/test_t05_word_karaoke.py::test_main_passes_subs_mode_to_render_one
9 failed, 1 passed, 7 skipped in 0.40s
```
