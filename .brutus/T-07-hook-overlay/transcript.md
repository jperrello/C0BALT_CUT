# T-07 hook overlay — red phase

*2026-05-05T22:28:35Z by Showboat 0.6.1*
<!-- showboat-id: b4034ca6-550e-4901-9a52-2ccb573cecb1 -->

Spec: --overlay={off,on} default on. For each shortlisted clip the ranker calls scribe (service crew via tmux send) to get a 5-7 word TikTok-grammar overlay line, rendered as ASS title at top of frame (Alignment=8 or \\an8). Scribe inputs: transcript snippet + hook_score features. Smoke: three eval VODs each render with a distinct legible overlay, verified by top-band bright-pixel coverage; --overlay=off keeps top band dark. Test seam: SCRIBE_STUB env var lets tests drive deterministic scribe responses without live tmux. Tests below MUST be red — they prove the behavior is missing.

```bash
pytest tests/test_t07_hook_overlay.py --no-header -q 2>&1 | tail -20
```

```output
            "request_overlay never called from main/ranker shortlist loop"
E       AssertionError: request_overlay never called from main/ranker shortlist loop
E       assert 'request_overlay(' in '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport argparse\nimport json\nimport math\nimport os\ni..."shorts": meta}, indent=2))\n    print(f"[v2] wrote {len(meta)} shorts")\n\n\nif __name__ == "__main__":\n    main()\n'

tests/test_t07_hook_overlay.py:156: AssertionError
=========================== short test summary info ============================
FAILED tests/test_t07_hook_overlay.py::test_overlay_flag_in_help - AssertionE...
FAILED tests/test_t07_hook_overlay.py::test_overlay_default_is_on - Assertion...
FAILED tests/test_t07_hook_overlay.py::test_request_overlay_function_exists
FAILED tests/test_t07_hook_overlay.py::test_request_overlay_signature_takes_transcript_and_features
FAILED tests/test_t07_hook_overlay.py::test_request_overlay_returns_5_to_7_words
FAILED tests/test_t07_hook_overlay.py::test_request_overlay_truncates_or_rejects_overlong_stub
FAILED tests/test_t07_hook_overlay.py::test_write_ass_overlay_function_exists
FAILED tests/test_t07_hook_overlay.py::test_write_ass_overlay_top_aligned - A...
FAILED tests/test_t07_hook_overlay.py::test_write_ass_overlay_includes_timing
FAILED tests/test_t07_hook_overlay.py::test_render_one_accepts_overlay_param
FAILED tests/test_t07_hook_overlay.py::test_main_threads_overlay_flag - Asser...
FAILED tests/test_t07_hook_overlay.py::test_overlay_off_disables_burn - Asser...
FAILED tests/test_t07_hook_overlay.py::test_ranker_invokes_request_overlay - ...
13 failed, 5 skipped in 0.21s
```
