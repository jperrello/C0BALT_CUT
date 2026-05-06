"""T-09 contract tests: A/B variant trim emitter.

For each top-N shortlisted moment, emit two variants whose lead windows
differ by 5s but whose payoff lands at the same absolute timestamp.
Naming: <bead>-<ts>-short-NN-a.mp4 / <bead>-<ts>-short-NN-b.mp4.
Both variants flow through the eval loop independently.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline_v2 as v2


# ---------- (a) variant window generator ----------

def test_variant_windows_function_exists():
    assert callable(getattr(v2, "variant_windows", None)), \
        "pipeline_v2.variant_windows(clip_start, clip_end, payoff_abs) -> list is missing"


def test_variant_windows_returns_two_pairs():
    pairs = v2.variant_windows(100.0, 145.0, payoff_abs=110.0)
    assert isinstance(pairs, list) and len(pairs) == 2, \
        f"variant_windows must return exactly 2 (cs, ce) pairs, got {pairs}"
    for p in pairs:
        assert len(p) == 2, f"each pair must be (cs, ce), got {p}"
        cs, ce = p
        assert isinstance(cs, float) and isinstance(ce, float)


def test_variant_windows_lead_differs_by_5s():
    """The two variant clip_starts must differ by exactly 5.0s (the ±5s lead shift)."""
    (cs_a, _), (cs_b, _) = v2.variant_windows(100.0, 145.0, payoff_abs=110.0)
    diff = abs(cs_a - cs_b)
    assert abs(diff - 5.0) < 0.01, \
        f"variant clip_starts must differ by 5.0s (lead shift), got {diff:.3f}"


def test_variant_windows_payoff_preserved():
    """Both variants must contain the payoff at the SAME absolute timestamp.

    Falsifiable: variant A starts at 100s, variant B starts at 105s; payoff
    at absolute t=110s falls 10s into A and 5s into B but lands at the same
    moment in both. Both clips must contain t=110s within [cs, ce]."""
    payoff = 110.0
    pairs = v2.variant_windows(100.0, 145.0, payoff_abs=payoff)
    for cs, ce in pairs:
        assert cs <= payoff <= ce, \
            f"variant ({cs}, {ce}) does not contain payoff at {payoff}"


def test_variant_windows_lengths_in_band():
    """Both windows must satisfy the v2 duration band (25 ≤ dur ≤ 65)."""
    pairs = v2.variant_windows(100.0, 145.0, payoff_abs=120.0)
    for cs, ce in pairs:
        d = ce - cs
        assert 25.0 <= d <= 65.0, \
            f"variant duration {d:.2f}s out of [25, 65] band: ({cs}, {ce})"


def test_variant_windows_distinct_starts():
    """The two variants must be genuinely different clips (not duplicates)."""
    (cs_a, ce_a), (cs_b, ce_b) = v2.variant_windows(100.0, 145.0, payoff_abs=110.0)
    assert (cs_a, ce_a) != (cs_b, ce_b), "two variants are identical"


# ---------- (b) main loop emits two variants per moment ----------

def test_main_uses_variant_windows():
    src = (ROOT / "pipeline_v2.py").read_text()
    assert "variant_windows" in src, \
        "main never calls variant_windows — single-clip path still in place"


def test_naming_pattern_a_b_suffix():
    """The render loop must produce `-a` / `-b` suffixed file stems for each
    shortlisted moment."""
    src = (ROOT / "pipeline_v2.py").read_text()
    # Either f-string templates or literals — both acceptable; verify both
    # variant labels appear in the render-loop region.
    assert re.search(r"short-[^.\s]*-a", src) or "'-a'" in src or '"-a"' in src, \
        "no '-a' variant naming found in render loop"
    assert re.search(r"short-[^.\s]*-b", src) or "'-b'" in src or '"-b"' in src, \
        "no '-b' variant naming found in render loop"


def test_each_variant_calls_deliver_and_grade():
    """Both variants must flow through deliver() (which calls grade())."""
    src = (ROOT / "pipeline_v2.py").read_text()
    # Find the render loop region — between `for i, c in enumerate(final` and the meta append boundary
    m = re.search(r"for i, c in enumerate\(final.*?(?=\n    \(args\.outdir|\nif __name__)", src, re.S)
    assert m, "could not locate the render loop region in main()"
    region = m.group(0)
    # Two deliver() calls (one per variant) OR one deliver call inside a per-variant inner loop
    deliver_calls = region.count("deliver(")
    inner_loop = re.search(r"for\s+\w+\s+in\s+(?:variant_windows|pairs|variants)", region)
    assert deliver_calls >= 2 or (inner_loop and deliver_calls >= 1), \
        f"render loop must deliver each variant — found {deliver_calls} deliver() calls, " \
        f"inner-variant-loop={'yes' if inner_loop else 'no'}"


# ---------- (c) shorts.json sidecar exposes per-variant payoff ----------

def test_shorts_json_meta_includes_payoff_abs():
    """Per-variant meta must expose payoff_abs so downstream tooling can
    confirm payoff alignment between variant pairs."""
    src = (ROOT / "pipeline_v2.py").read_text()
    assert "payoff_abs" in src, \
        "shorts.json meta must include 'payoff_abs' per variant for alignment verification"


def test_shorts_json_meta_includes_variant_label():
    """Per-variant meta must include a 'variant' label ('a' or 'b') so the
    pair can be correlated."""
    src = (ROOT / "pipeline_v2.py").read_text()
    assert re.search(r"['\"]variant['\"]", src), \
        "shorts.json meta must include a 'variant' field labelling 'a'/'b'"


# ---------- (d) smoke: real variant pair on tyler1 ----------

TYLER1 = ROOT / "source" / "vod-tyler1-jynxzi.mp4"


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1" or not TYLER1.exists(),
    reason="set RUN_SMOKE=1 and ensure source/vod-tyler1-jynxzi.mp4 is present",
)
def test_smoke_variant_pair_emitted_per_moment(tmp_path):
    """Run main on tyler1 with --n=1; expect TWO files in the shorts dir
    (short-01-a.mp4 + short-01-b.mp4), and BOTH delivered to delivered/
    after passing the eval loop (or both rejected — but the pair must be
    processed independently)."""
    outdir = tmp_path / "ab"
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(TYLER1), str(outdir),
         "--n", "1"],
        check=True,
    )
    sidecar = outdir / "shorts.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    shorts = data["shorts"]

    # Exactly 2 entries for n=1 (a + b)
    assert len(shorts) == 2, \
        f"--n=1 must emit 2 variants, got {len(shorts)}: {[s.get('file') for s in shorts]}"

    labels = sorted(s["variant"] for s in shorts)
    assert labels == ["a", "b"], f"variant labels must be ['a','b'], got {labels}"

    # Both files must exist on disk
    for s in shorts:
        f = ROOT / s["file"]
        assert f.exists(), f"variant file missing: {f}"
        assert "-a.mp4" in s["file"] or "-b.mp4" in s["file"], \
            f"variant filename does not match -a/-b pattern: {s['file']}"


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1" or not TYLER1.exists(),
    reason="set RUN_SMOKE=1",
)
def test_smoke_variant_pair_payoff_aligned(tmp_path):
    """The two variants of one moment must share a payoff_abs (within 0.5s)
    while having distinct clip_starts."""
    outdir = tmp_path / "ab2"
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(TYLER1), str(outdir),
         "--n", "1"],
        check=True,
    )
    shorts = json.loads((outdir / "shorts.json").read_text())["shorts"]
    by_label = {s["variant"]: s for s in shorts}
    a, b = by_label["a"], by_label["b"]

    assert abs(a["payoff_abs"] - b["payoff_abs"]) < 0.5, \
        f"payoff drift between variants: a={a['payoff_abs']} b={b['payoff_abs']}"
    assert abs(a["source_start"] - b["source_start"]) > 1.0, \
        f"variant starts not distinct enough: a={a['source_start']} b={b['source_start']}"
