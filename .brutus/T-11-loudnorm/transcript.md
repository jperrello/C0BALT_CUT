# T-11 loudnorm normalization — red phase

*2026-05-06T02:17:16Z by Showboat 0.6.1*
<!-- showboat-id: b972bcc4-42b4-442a-b2f3-c58068b7418f -->

Spec: change encode loudnorm filter from TP=-1 to TP=-1.5 (single-pass per user direction). Falsifiable: re-rendered tyler1 + medium clips measure loudnorm_i in [-15,-13], i.e. survive the T-08 grader's loudnorm hard-fail. Counter-proposal note: ffmpeg single-pass loudnorm does dynamic compression, not linear normalization to I — moving from -17 LUFS to -14 reliably typically requires two-pass (measure then apply with linear=true + measured values). Tests below MUST be red on the TP literal change at minimum; smoke is the real oracle.

```bash
pytest tests/test_t11_loudnorm.py --no-header -q 2>&1 | tail -10
```

```output
                f"encode loudnorm must use TP=-1.5 (T-11 change), got: {f}"
E           AssertionError: encode loudnorm must use TP=-1.5 (T-11 change), got: loudnorm=I=-14:LRA=11:TP=-1
E           assert None
E            +  where None = <function search at 0x103a49850>('\\bTP=-1\\.5\\b', 'loudnorm=I=-14:LRA=11:TP=-1')
E            +    where <function search at 0x103a49850> = re.search

tests/test_t11_loudnorm.py:54: AssertionError
=========================== short test summary info ============================
FAILED tests/test_t11_loudnorm.py::test_encode_loudnorm_tp_minus_1_5 - Assert...
1 failed, 3 passed, 3 skipped in 0.23s
```
