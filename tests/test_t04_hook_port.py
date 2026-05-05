"""T-04 contract tests: hook scorer port + composite ranker + variety re-rank.

These are the red-phase falsifiable assertions for porting v1 hook scoring
into pipeline_v2.py. Smoke test gated behind RUN_SMOKE=1.
"""
import math
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline_v2 as v2


# ---------- (a) HOOK_WORDS + hook_score ported ----------

def test_hook_words_set_present():
    assert isinstance(v2.HOOK_WORDS, set)
    for w in ("wait", "bro", "yo", "bruh", "damn"):
        assert w in v2.HOOK_WORDS


def test_hook_score_callable():
    assert callable(getattr(v2, "hook_score", None)), \
        "pipeline_v2.hook_score is missing — port it from pipeline.py:160"


def test_hook_score_distinguishes_hook_from_neutral():
    """Hook word in first 3s must score strictly higher than neutral text."""
    import numpy as np
    rms_clip = np.array([0.1, 0.1, 0.1, 0.1, 0.1])
    hook_segs = [{"start": 0.0, "end": 1.5, "text": "wait what bro"}]
    neutral_segs = [{"start": 0.0, "end": 1.5, "text": "and then we walked"}]
    hs_hook = v2.hook_score(hook_segs, rms_clip, 0.0)
    hs_neutral = v2.hook_score(neutral_segs, rms_clip, 0.0)
    # Accept either (float, bool) tuple or float return shape.
    sh = hs_hook[0] if isinstance(hs_hook, tuple) else hs_hook
    sn = hs_neutral[0] if isinstance(hs_neutral, tuple) else hs_neutral
    assert sh > sn, f"hook text scored {sh}, neutral scored {sn}"
    assert sh >= 1.0, f"hook word match must contribute at least 1.0, got {sh}"


def test_hook_score_empty_segs_zero():
    import numpy as np
    res = v2.hook_score([], np.array([0.0]), 0.0)
    s = res[0] if isinstance(res, tuple) else res
    assert s == 0.0


# ---------- (b) composite score energy*log(density) + alpha*hook_score ----------

def test_composite_score_function_exists():
    assert callable(getattr(v2, "composite_score", None)), \
        "pipeline_v2.composite_score(cand) -> float is missing"


def test_composite_score_promotes_hook_bearing_candidate():
    """Two cands with equal base score; the one with hook_score>0 wins."""
    a = {"score": 1.0, "hook_score": 0.0}
    b = {"score": 1.0, "hook_score": 2.0}
    assert v2.composite_score(b) > v2.composite_score(a)


def test_composite_score_alpha_positive_and_sane():
    """alpha must be in (0, 10] — proves hook contributes but doesn't dominate."""
    base = {"score": 0.0, "hook_score": 1.0}
    zero = {"score": 0.0, "hook_score": 0.0}
    delta = v2.composite_score(base) - v2.composite_score(zero)
    assert 0.0 < delta <= 10.0, f"alpha out of sane range, delta={delta}"


# ---------- (c) features hook_in_first_3s, standalone_3s, duration_fit ----------

def test_score_features_function_exists():
    assert callable(getattr(v2, "score_features", None)), \
        "pipeline_v2.score_features(segs, rms_clip, cs, ce) -> dict is missing"


def test_score_features_keys_present():
    import numpy as np
    segs = [{"start": 0.0, "end": 2.5, "text": "wait what is happening"}]
    feats = v2.score_features(segs, np.array([0.1] * 45), 0.0, 45.0)
    assert isinstance(feats, dict)
    for k in ("hook_in_first_3s", "standalone_3s", "duration_fit"):
        assert k in feats, f"missing feature key: {k}"
    assert isinstance(feats["hook_in_first_3s"], bool)
    assert isinstance(feats["standalone_3s"], bool)
    assert isinstance(feats["duration_fit"], float)


def test_hook_in_first_3s_true_when_hook_word_in_head():
    import numpy as np
    segs = [{"start": 0.5, "end": 2.0, "text": "bro this is insane"}]
    feats = v2.score_features(segs, np.array([0.1] * 45), 0.0, 45.0)
    assert feats["hook_in_first_3s"] is True


def test_hook_in_first_3s_false_when_hook_word_after_3s():
    import numpy as np
    segs = [
        {"start": 0.0, "end": 2.5, "text": "and then we walked over"},
        {"start": 5.0, "end": 6.5, "text": "bro this is insane"},
    ]
    feats = v2.score_features(segs, np.array([0.1] * 45), 0.0, 45.0)
    assert feats["hook_in_first_3s"] is False


def test_duration_fit_peaks_near_45s():
    """duration_fit should be highest near the 45s target window."""
    import numpy as np
    rms = np.array([0.1] * 60)
    f45 = v2.score_features([], rms, 0.0, 45.0)["duration_fit"]
    f20 = v2.score_features([], rms, 0.0, 20.0)["duration_fit"]
    f60 = v2.score_features([], rms, 0.0, 60.0)["duration_fit"]
    assert f45 >= f20 and f45 >= f60, \
        f"duration_fit not maximized near 45s: 20s={f20} 45s={f45} 60s={f60}"


# ---------- (d) variety / 10-minute min-gap re-ranker ----------

def test_pick_variety_function_exists():
    fn = getattr(v2, "pick_variety", None)
    assert callable(fn), "pipeline_v2.pick_variety(cands, n, min_gap=600.0) is missing"


def test_pick_variety_enforces_10min_gap():
    """Two top-scored moments within the same 10-min window must not co-occur."""
    cands = [
        {"start": 0.0, "end": 45.0, "score": 5.0, "hook_score": 0.0,
         "clip_start": 0.0, "clip_end": 45.0},
        {"start": 120.0, "end": 165.0, "score": 4.9, "hook_score": 0.0,
         "clip_start": 120.0, "clip_end": 165.0},
        {"start": 700.0, "end": 745.0, "score": 4.5, "hook_score": 0.0,
         "clip_start": 700.0, "clip_end": 745.0},
        {"start": 1400.0, "end": 1445.0, "score": 4.0, "hook_score": 0.0,
         "clip_start": 1400.0, "clip_end": 1445.0},
    ]
    chosen = v2.pick_variety(cands, n=2, min_gap=600.0)
    assert len(chosen) == 2
    starts = sorted(c["start"] for c in chosen)
    assert starts[1] - starts[0] >= 600.0, \
        f"min-gap violated: chose {starts}"


def test_pick_variety_default_min_gap_is_600():
    """Default min_gap must be 10 minutes per the T-04 spec."""
    import inspect
    sig = inspect.signature(v2.pick_variety)
    default = sig.parameters["min_gap"].default
    assert default == 600.0, f"default min_gap must be 600.0, got {default}"


# ---------- legacy energy-only path removed ----------

def test_legacy_energy_only_pick_removed_from_main():
    """The old `final = pick(cands, n=args.n)` direct call must be gone.

    The composite path replaces it with a shortlist→transcribe→rescore→variety chain.
    """
    src = (ROOT / "pipeline_v2.py").read_text()
    # The exact legacy line from pipeline_v2.py:579 before the port.
    assert "final = pick(cands, n=args.n)" not in src, \
        "legacy energy-only path still present at the line that should be replaced"


def test_main_flow_invokes_hook_rescore():
    """Main must reference hook_score / composite_score in the candidate ranking."""
    src = (ROOT / "pipeline_v2.py").read_text()
    assert "hook_score" in src, "hook_score not wired into pipeline_v2 main flow"
    assert "composite_score" in src or "pick_variety" in src, \
        "composite ranker / variety re-rank not wired in"


# ---------- smoke: first 3s of delivered short contains a HOOK_WORDS word ----------

SMOKE_SRC = ROOT / "source" / "vod-tyler1-jynxzi.mp4"


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1" or not SMOKE_SRC.exists(),
    reason="set RUN_SMOKE=1 and ensure source/vod-tyler1-jynxzi.mp4 is fully downloaded",
)
def test_smoke_tyler1_first_3s_has_hook_word(tmp_path):
    """End-to-end oracle: top-1 delivered short's first 3s transcript
    must contain a HOOK_WORDS interjection, and top-2 shortlisted
    moments must be ≥600s apart."""
    import json
    import subprocess

    outdir = tmp_path / "smoke"
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(SMOKE_SRC), str(outdir),
         "--n", "2"],
        check=True,
    )
    sidecar = json.loads((outdir / "shorts.json").read_text())
    shorts = sidecar["shorts"]
    assert len(shorts) >= 2

    # min-gap on the chosen pair
    starts = sorted(s["source_start"] for s in shorts[:2])
    assert starts[1] - starts[0] >= 600.0, f"top-2 within 10min: {starts}"

    # first 3s of short-01 contains a hook word
    short1 = shorts[0]
    head_text = " ".join(
        t["text"] for t in short1.get("transcript", []) if t["start"] < 3.0
    ).lower()
    words = {w.strip(".,!?") for w in head_text.split()}
    assert words & v2.HOOK_WORDS, \
        f"no HOOK_WORDS in first 3s of short-01: {head_text!r}"
