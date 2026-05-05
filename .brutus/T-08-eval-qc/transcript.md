# T-08 eval/QC loop — red phase

*2026-05-05T22:16:45Z by Showboat 0.6.1*
<!-- showboat-id: de5faaca-02bb-41c5-ade4-fd032c439959 -->

Spec: grader runs after every render. Hard fails (file<100KB, duration<25 or >65, loudnorm I outside [-15,-13], face-tile black >50%, transcript empty) auto-move via shutil.move to delivered/rejected/<reason>/ — never delete. Soft flags (reframe jerk, hook-window energy, no first-3s interjection) warn in verdict, keep in delivered/. Sidecar <stem>.verdict.json next to every render. Wired into pipeline_v2.deliver(). Smoke: synthetic 10s mp4 → moved to delivered/rejected/duration/ with verdict.json describing rejection. Tests below MUST be red — they prove the behavior is missing.

```bash
cd /Users/jperr/Documents/shorts && pytest tests/test_t08_eval_qc.py --no-header -q 2>&1 | tail -28
```

```output
E       AttributeError: module 'pipeline_v2' has no attribute 'grade_metrics'

tests/test_t08_eval_qc.py:240: AttributeError
=========================== short test summary info ============================
FAILED tests/test_t08_eval_qc.py::test_evaluate_function_exists - AssertionEr...
FAILED tests/test_t08_eval_qc.py::test_grade_metrics_function_exists - Assert...
FAILED tests/test_t08_eval_qc.py::test_grade_function_exists - AssertionError...
FAILED tests/test_t08_eval_qc.py::test_evaluate_verdict_schema_keys - Attribu...
FAILED tests/test_t08_eval_qc.py::test_evaluate_healthy_passes - AttributeErr...
FAILED tests/test_t08_eval_qc.py::test_evaluate_rejects_each_hard_fail[override0-size]
FAILED tests/test_t08_eval_qc.py::test_evaluate_rejects_each_hard_fail[override1-duration]
FAILED tests/test_t08_eval_qc.py::test_evaluate_rejects_each_hard_fail[override2-duration]
FAILED tests/test_t08_eval_qc.py::test_evaluate_rejects_each_hard_fail[override3-loudnorm]
FAILED tests/test_t08_eval_qc.py::test_evaluate_rejects_each_hard_fail[override4-loudnorm]
FAILED tests/test_t08_eval_qc.py::test_evaluate_rejects_each_hard_fail[override5-face_black]
FAILED tests/test_t08_eval_qc.py::test_evaluate_rejects_each_hard_fail[override6-transcript_empty]
FAILED tests/test_t08_eval_qc.py::test_evaluate_soft_flags_warn_but_keep[override0-reframe_jerk]
FAILED tests/test_t08_eval_qc.py::test_evaluate_soft_flags_warn_but_keep[override1-low_hook_energy]
FAILED tests/test_t08_eval_qc.py::test_evaluate_soft_flags_warn_but_keep[override2-no_interjection_first_3s]
FAILED tests/test_t08_eval_qc.py::test_evaluate_loudnorm_band_is_minus15_to_minus13
FAILED tests/test_t08_eval_qc.py::test_evaluate_duration_band_is_25_to_65 - A...
FAILED tests/test_t08_eval_qc.py::test_grade_writes_verdict_sidecar_alongside_healthy
FAILED tests/test_t08_eval_qc.py::test_grade_moves_rejected_short_clip_to_duration_subdir
FAILED tests/test_t08_eval_qc.py::test_grade_never_deletes_uses_shutil_move
FAILED tests/test_t08_eval_qc.py::test_deliver_invokes_grader - AssertionErro...
FAILED tests/test_t08_eval_qc.py::test_rejection_subdir_named_after_reason - ...
FAILED tests/test_t08_eval_qc.py::test_smoke_real_metrics_on_synth_mp4_rejects_short
23 failed in 1.44s
```
