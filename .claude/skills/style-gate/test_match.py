import json, os, sys, subprocess, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "style-corpus"))
import match, moves, accept, distill


def profile(cpm=20.0, med=2.5, gap=6.0, wpm=150.0, cut=0.2):
    return {"style_profile_version": 1, "clip": "x.mp4", "duration_sec": 40.0,
            "cuts": {"cuts_per_min": cpm, "median_shot_sec": med,
                     "p90_shot_sec": 5.0, "longest_static_gap": gap},
            "speech": {"words_per_min": wpm, "max_silence_sec": 0.5, "speech_fraction": 0.9},
            "visual": {"cutaway_fraction": cut, "face_fraction": 1 - cut, "cutaway_count": 4},
            "captions": {"present_fraction": 0.8}, "audio": {}, "hook": {}, "vision": {},
            "meta": {}}


def targets():
    refs = [profile(cpm=34 + i, med=1.4, gap=4.0 + 0.2 * i, wpm=185 + 3 * i, cut=0.45)
            for i in range(4)]
    return distill.distill(refs)


class Match(unittest.TestCase):
    def test_match_within_band(self):
        v = match.compare(profile(cpm=34.5, med=1.45, gap=4.2, wpm=186, cut=0.44), targets())
        self.assertTrue(v["match"])

    def test_mismatch_carries_lever_and_dir(self):
        v = match.compare(profile(cpm=12.0, med=3.5, gap=9.0, wpm=140, cut=0.1), targets())
        self.assertFalse(v["match"])
        top = v["mismatches"][0]
        self.assertIn("lever", top)
        self.assertIn(top["dir"], ("up", "down"))
        by = {m["field"]: m for m in v["mismatches"]}
        # cuts_per_min below target, invert=True -> lever JUMP_CUT_SEG moves DOWN
        self.assertEqual(by["cuts.cuts_per_min"]["dir"], "down")
        # median_shot_sec above target, invert=False -> lever moves DOWN
        self.assertEqual(by["cuts.median_shot_sec"]["dir"], "down")

    def test_diagnostic_never_fails(self):
        t = targets()
        p = profile(cpm=34.5, med=1.45, gap=4.2, wpm=186, cut=0.44)
        p["duration_sec"] = 500.0            # wildly off, but diagnostic
        self.assertTrue(match.compare(p, t)["match"])

    def test_small_corpus_noop(self):
        t = targets()
        t["n"] = 1
        v = match.compare(profile(cpm=1.0), t)
        self.assertTrue(v["match"])
        self.assertIn("skipped", v)

    def test_version_mismatch_noop(self):
        t = targets()
        t["style_profile_version"] = 99
        self.assertTrue(match.compare(profile(), t)["match"])


class Moves(unittest.TestCase):
    def test_moves_clamped_and_bounded(self):
        v = match.compare(profile(cpm=5.0, med=6.0, gap=12.0, wpm=120, cut=0.0), targets())
        plan = moves.plan(v)
        self.assertLessEqual(len(plan), moves.MAXMOVES)
        for k, val in plan.items():
            spec = moves.KNOBS[k]
            self.assertGreaterEqual(val, spec["min"])
            self.assertLessEqual(val, spec["max"])

    def test_no_moves_on_match(self):
        self.assertEqual(moves.plan({"match": True, "mismatches": []}), {})


class Accept(unittest.TestCase):
    def v(self, fields):
        return {"match": not fields,
                "mismatches": [{"field": f, "z": z, "lever": "SPEED", "dir": "up"}
                               for f, z in fields.items()],
                "diagnostic": []}

    def test_full_match_passes(self):
        self.assertTrue(accept.passes(self.v({"a": 3.0}), self.v({})))

    def test_improvement_passes(self):
        self.assertTrue(accept.passes(self.v({"a": 3.0, "b": 2.0}), self.v({"a": 1.8, "b": 2.0})))

    def test_regression_rejects(self):
        self.assertFalse(accept.passes(self.v({"a": 2.0}), self.v({"a": 3.0})))

    def test_new_mismatch_rejects(self):
        self.assertFalse(accept.passes(self.v({"a": 3.0}), self.v({"a": 2.0, "c": 2.0})))

    def test_no_change_rejects(self):
        self.assertFalse(accept.passes(self.v({"a": 3.0}), self.v({"a": 3.0})))


if __name__ == "__main__":
    unittest.main()
