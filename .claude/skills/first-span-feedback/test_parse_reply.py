import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_reply import verdict


def check(name, got, want):
    if got != want:
        print("FAIL %s\n  got:  %s\n  want: %s" % (name, got, want))
        sys.exit(1)
    print("ok   %s" % name)


# clean verdict -> defect false
check("clean",
      verdict('{"defect": false}'),
      {"defect": False})

# clean verdict wrapped in prose/fences still parses to defect false
check("clean_fenced",
      verdict('Here is my read:\n```json\n{"defect": false, "rationale": "looks good"}\n```'),
      {"defect": False})

# defect verdict -> all fields normalized
check("defect",
      verdict('```json\n{"defect": true, "defect_class": "wrong_person", '
              '"signal": "frame1_is_face", "where": "fill-vertical", '
              '"rationale": "cold open hero-frames the listener"}\n```'),
      {"defect": True, "defect_class": "wrong_person", "signal": "frame1_is_face",
       "where": "fill-vertical", "rationale": "cold open hero-frames the listener"})

# defect with a string "null" signal collapses to None
check("defect_null_signal",
      verdict('{"defect": true, "defect_class": "flat_hook", "signal": "null", '
              '"where": "pick-segments", "rationale": "no curiosity gap"}'),
      {"defect": True, "defect_class": "flat_hook", "signal": None,
       "where": "pick-segments", "rationale": "no curiosity gap"})

# malformed / non-JSON -> fail-safe clean
check("malformed", verdict("not json at all {broken"), {"defect": False})
check("empty", verdict(""), {"defect": False})
check("no_defect_key", verdict('{"summary": "hi"}'), {"defect": False})

print("\nall parse_reply tests passed")
