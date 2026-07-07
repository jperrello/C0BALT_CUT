import os, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import distill


def profile(cpm):
    return {"style_profile_version": 1, "clip": "c%g.mp4" % cpm,
            "duration_sec": 40.0,
            "cuts": {"cuts_per_min": cpm, "median_shot_sec": 60.0 / max(cpm, 1)},
            "speech": {}, "visual": {}, "captions": {}, "audio": {},
            "hook": {}, "vision": {}, "meta": {}}


class Distill(unittest.TestCase):
    def test_robust_stats(self):
        t = distill.distill([profile(c) for c in (30, 34, 36, 38, 200)])  # outlier
        f = t["fields"]["cuts.cuts_per_min"]
        self.assertEqual(f["n"], 5)
        self.assertLess(f["median"], 40)     # outlier does not drag the median
        self.assertEqual(f["lever"], "JUMP_CUT_SEG")
        self.assertTrue(f["invert"])

    def test_sigma_floor(self):
        t = distill.distill([profile(34.0)] * 4)  # degenerate corpus
        f = t["fields"]["cuts.cuts_per_min"]
        self.assertGreaterEqual(f["sigma"], 3.4 - 1e-6)   # 10% of median floor

    def test_missing_fields_skipped(self):
        t = distill.distill([profile(30), profile(36)])
        self.assertNotIn("speech.words_per_min", t["fields"])


if __name__ == "__main__":
    unittest.main()
