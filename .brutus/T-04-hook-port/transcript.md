# T-04 hook port — red phase

*2026-05-05T21:19:50Z by Showboat 0.6.1*
<!-- showboat-id: c305646d-4f80-4d15-b33a-5d8fad9dc94a -->

Spec: Port v1 hook scoring into pipeline_v2. Composite ranker = energy*log(density) + alpha*hook_score. Add hook_in_first_3s, standalone_3s, duration_fit features. Variety re-rank enforces 10-min min gap between consecutive shortlisted moments. Smoke oracle: tyler1 vod top-1 short first 3s contains a HOOK_WORDS interjection AND top-2 starts >=600s apart. Tests below MUST be red — they prove the behavior is missing.

```bash
python3 -m pytest tests/test_t04_hook_port.py --no-header -q 2>&1 | tail -25
```

```output
/Users/jperr/.cache/uv/archive-v0/sOzsRhPmu6jhLisaHpc9s/bin/python3: No module named pytest
```

```bash
pytest tests/test_t04_hook_port.py --no-header -q 2>&1 | tail -25
```

```output
        """Main must reference hook_score / composite_score in the candidate ranking."""
        src = (ROOT / "pipeline_v2.py").read_text()
>       assert "hook_score" in src, "hook_score not wired into pipeline_v2 main flow"
E       AssertionError: hook_score not wired into pipeline_v2 main flow
E       assert 'hook_score' in '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport argparse\nimport json\nimport math\nimport os\ni..."shorts": meta}, indent=2))\n    print(f"[v2] wrote {len(meta)} shorts")\n\n\nif __name__ == "__main__":\n    main()\n'

tests/test_t04_hook_port.py:173: AssertionError
=========================== short test summary info ============================
FAILED tests/test_t04_hook_port.py::test_hook_score_callable - AssertionError...
FAILED tests/test_t04_hook_port.py::test_hook_score_distinguishes_hook_from_neutral
FAILED tests/test_t04_hook_port.py::test_hook_score_empty_segs_zero - Attribu...
FAILED tests/test_t04_hook_port.py::test_composite_score_function_exists - As...
FAILED tests/test_t04_hook_port.py::test_composite_score_promotes_hook_bearing_candidate
FAILED tests/test_t04_hook_port.py::test_composite_score_alpha_positive_and_sane
FAILED tests/test_t04_hook_port.py::test_score_features_function_exists - Ass...
FAILED tests/test_t04_hook_port.py::test_score_features_keys_present - Attrib...
FAILED tests/test_t04_hook_port.py::test_hook_in_first_3s_true_when_hook_word_in_head
FAILED tests/test_t04_hook_port.py::test_hook_in_first_3s_false_when_hook_word_after_3s
FAILED tests/test_t04_hook_port.py::test_duration_fit_peaks_near_45s - Attrib...
FAILED tests/test_t04_hook_port.py::test_pick_variety_function_exists - Asser...
FAILED tests/test_t04_hook_port.py::test_pick_variety_enforces_10min_gap - At...
FAILED tests/test_t04_hook_port.py::test_pick_variety_default_min_gap_is_600
FAILED tests/test_t04_hook_port.py::test_legacy_energy_only_pick_removed_from_main
FAILED tests/test_t04_hook_port.py::test_main_flow_invokes_hook_rescore - Ass...
16 failed, 1 passed, 1 skipped in 0.16s
```
