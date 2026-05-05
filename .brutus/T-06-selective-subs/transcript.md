# T-06 selective subs — red phase

*2026-05-05T23:08:09Z by Showboat 0.6.1*
<!-- showboat-id: e9d0fc76-a32e-495c-8973-2b61e0653345 -->

Spec: --subs-mode={line,word,selective} default selective. Local-signal tagger fires on RMS z>1.5 OR HOOK_WORDS interjection OR scene cut within 1s. Each candidate span routed to judge crew via tmux for Y/N. Renderer burns ASS dialogue ONLY for segs overlapping engaging=true spans. Test seam: JUDGE_STUB env var (single Y/N or comma-separated sequence) lets tests drive deterministic judge responses. Smoke (vod-podcast 60s clip): subtitle_spans.json sidecar shows engaging coverage <85% of clip duration (visible non-subtitled stretches), each engaging span's reason in {rms_peak, hook_word, scene_cut, judge}. Tests below MUST be red — they prove the behavior is missing.

```bash
pytest tests/test_t06_selective_subs.py --no-header -q 2>&1 | tail -22
```

```output
tests/test_t06_selective_subs.py:207: AssertionError
=========================== short test summary info ============================
FAILED tests/test_t06_selective_subs.py::test_subs_mode_default_is_selective
FAILED tests/test_t06_selective_subs.py::test_subs_mode_choices_include_selective
FAILED tests/test_t06_selective_subs.py::test_tag_candidate_spans_function_exists
FAILED tests/test_t06_selective_subs.py::test_tag_fires_on_rms_peak - Attribu...
FAILED tests/test_t06_selective_subs.py::test_tag_fires_on_hook_word - Attrib...
FAILED tests/test_t06_selective_subs.py::test_tag_fires_on_scene_cut - Attrib...
FAILED tests/test_t06_selective_subs.py::test_tag_returns_empty_when_no_signal
FAILED tests/test_t06_selective_subs.py::test_judge_span_function_exists - As...
FAILED tests/test_t06_selective_subs.py::test_judge_span_honors_stub_yes - At...
FAILED tests/test_t06_selective_subs.py::test_judge_span_honors_stub_no - Att...
FAILED tests/test_t06_selective_subs.py::test_judge_span_consumes_sequence - ...
FAILED tests/test_t06_selective_subs.py::test_select_engaging_spans_function_exists
FAILED tests/test_t06_selective_subs.py::test_select_engaging_spans_filters_by_judge
FAILED tests/test_t06_selective_subs.py::test_write_ass_selective_function_exists
FAILED tests/test_t06_selective_subs.py::test_write_ass_selective_skips_non_engaging
FAILED tests/test_t06_selective_subs.py::test_write_ass_selective_no_engaging_means_no_dialogue
FAILED tests/test_t06_selective_subs.py::test_write_ass_selective_preserves_locked_style
FAILED tests/test_t06_selective_subs.py::test_main_threads_selective_mode - A...
FAILED tests/test_t06_selective_subs.py::test_render_one_dispatches_on_selective
19 failed, 2 skipped in 0.27s
```
