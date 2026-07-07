import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_grade import cleared, passes


def g(grade=70, signals=None, caps=None):
    return {"grade": grade, "signals": signals or {}, "hard_caps": caps or []}


def check(name, got, want):
    if bool(got) != bool(want):
        print("FAIL %s\n  got:  %s\n  want: %s" % (name, got, want))
        sys.exit(1)
    print("ok   %s" % name)


# ---- grade regression is rejected regardless of signal ---------------------
prev = g(70, {"frame1_is_face": True})
check("regression_reject",
      passes(prev, g(60, {"frame1_is_face": True}), "frame1_is_face"), False)
check("no_regression_pass",
      passes(prev, g(72, {"frame1_is_face": True}), "frame1_is_face"), True)
check("equal_grade_pass",
      passes(prev, g(70, {"frame1_is_face": True}), "frame1_is_face"), True)

# ---- per-signal polarity ---------------------------------------------------
# frame1_is_face must be True (and no face_withheld cap)
check("frame1_true_clears", cleared(g(signals={"frame1_is_face": True}), "frame1_is_face"), True)
check("frame1_false_fails", cleared(g(signals={"frame1_is_face": False}), "frame1_is_face"), False)
check("frame1_true_but_cap_fails",
      cleared(g(signals={"frame1_is_face": True}, caps=["face_withheld"]), "frame1_is_face"), False)

# letterbox_bars / credit_lit_at_open must be False
check("letterbox_false_clears", cleared(g(signals={"letterbox_bars": False}), "letterbox_bars"), True)
check("letterbox_true_fails", cleared(g(signals={"letterbox_bars": True}), "letterbox_bars"), False)
check("credit_false_clears", cleared(g(signals={"credit_lit_at_open": False}), "credit_lit_at_open"), True)
check("credit_true_fails", cleared(g(signals={"credit_lit_at_open": True}), "credit_lit_at_open"), False)

# numeric lower-is-better with budget
check("silence_under_clears", cleared(g(signals={"max_residual_silence": 0.4}), "max_residual_silence"), True)
check("silence_over_fails", cleared(g(signals={"max_residual_silence": 1.5}), "max_residual_silence"), False)
check("payoff_under_clears", cleared(g(signals={"first_payoff_offset": 2.4}), "first_payoff_offset"), True)
check("payoff_over_fails", cleared(g(signals={"first_payoff_offset": 6.0}), "first_payoff_offset"), False)
check("payoff_null_fails", cleared(g(signals={"first_payoff_offset": None}), "first_payoff_offset"), False)
check("static_under_clears", cleared(g(signals={"longest_static_gap": 3.1}), "longest_static_gap"), True)
check("static_over_fails", cleared(g(signals={"longest_static_gap": 9.0}), "longest_static_gap"), False)

# numeric higher-is-better
check("caption_words_ok", cleared(g(signals={"opening_caption_words": 5}), "opening_caption_words"), True)
check("caption_words_thin_fails", cleared(g(signals={"opening_caption_words": 2}), "opening_caption_words"), False)
check("loop_high_clears", cleared(g(signals={"terminal_loop_score": 0.8}), "terminal_loop_score"), True)
check("loop_low_fails", cleared(g(signals={"terminal_loop_score": 0.1}), "terminal_loop_score"), False)

# hard-cap named directly
check("cap_absent_clears", cleared(g(caps=[]), "face_withheld"), True)
check("cap_present_fails", cleared(g(caps=["face_withheld"]), "face_withheld"), False)
check("cap_letterbox_present_fails", cleared(g(caps=["letterbox"]), "letterbox"), False)

# no signal -> grade-only gate (cleared True)
check("empty_signal_clears", cleared(g(), ""), True)
check("empty_signal_grade_only_pass", passes(g(70), g(75), ""), True)
check("empty_signal_grade_only_reject", passes(g(70), g(65), ""), False)

# unknown signal -> conservative fail
check("unknown_signal_fails", cleared(g(signals={"whatever": 1}), "banana"), False)
check("unknown_signal_blocks_pass", passes(g(70), g(80), "banana"), False)

print("\nall check_grade tests passed")
