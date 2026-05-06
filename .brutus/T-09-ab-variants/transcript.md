# T-09 A/B variant trim emitter — red phase

*2026-05-05T23:22:06Z by Showboat 0.6.1*
<!-- showboat-id: b009f6bd-afb1-4bf1-a6b0-117d27d03364 -->

Spec: For each top-N shortlisted moment, emit 2 variant clips that share a payoff_abs but differ by 5s in clip_start (lead shift). Naming: <bead>-<ts>-short-NN-a.mp4 / <bead>-<ts>-short-NN-b.mp4. Both variants flow through deliver()+grade() independently. shorts.json meta exposes per-variant payoff_abs and a 'variant' label ('a'/'b'). Smoke (tyler1 --n=1): exactly 2 entries in shorts.json with labels [a,b], both files exist, payoff_abs aligned within 0.5s, source_starts differ by >1s. Tests below MUST be red — they prove the variant emitter is missing.

```bash
pytest tests/test_t09_ab_variants.py --no-header -q 2>&1 | tail -15
```

```output

tests/test_t09_ab_variants.py:125: AssertionError
=========================== short test summary info ============================
FAILED tests/test_t09_ab_variants.py::test_variant_windows_function_exists - ...
FAILED tests/test_t09_ab_variants.py::test_variant_windows_returns_two_pairs
FAILED tests/test_t09_ab_variants.py::test_variant_windows_lead_differs_by_5s
FAILED tests/test_t09_ab_variants.py::test_variant_windows_payoff_preserved
FAILED tests/test_t09_ab_variants.py::test_variant_windows_lengths_in_band - ...
FAILED tests/test_t09_ab_variants.py::test_variant_windows_distinct_starts - ...
FAILED tests/test_t09_ab_variants.py::test_main_uses_variant_windows - Assert...
FAILED tests/test_t09_ab_variants.py::test_naming_pattern_a_b_suffix - Assert...
FAILED tests/test_t09_ab_variants.py::test_each_variant_calls_deliver_and_grade
FAILED tests/test_t09_ab_variants.py::test_shorts_json_meta_includes_payoff_abs
FAILED tests/test_t09_ab_variants.py::test_shorts_json_meta_includes_variant_label
11 failed, 2 skipped in 0.25s
```
