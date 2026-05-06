"""T-11 contract tests: loudnorm normalization in encode step.

Falsifiable claims:
1. Encode args carry loudnorm filter targeting I=-14, LRA=11, TP=-1.5.
2. Re-rendered tyler1 + medium clips measure loudnorm_i in [-15, -13]
   (i.e. survive the T-08 grader's loudnorm hard-fail).
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


# ---------- (a) encode args carry the right loudnorm filter ----------

def _encode_loudnorm_filters(src_text: str) -> list[str]:
    """All loudnorm=... filter strings in the source that include I= (excludes
    the measurement call which uses loudnorm=print_format=json)."""
    return [m for m in re.findall(r'loudnorm=[^"\']+', src_text) if 'I=' in m]


def test_encode_has_loudnorm_filter():
    filters = _encode_loudnorm_filters((ROOT / "pipeline_v2.py").read_text())
    assert filters, "no loudnorm encode filter (with I=) found in pipeline_v2.py"


def test_encode_loudnorm_targets_minus_14():
    filters = _encode_loudnorm_filters((ROOT / "pipeline_v2.py").read_text())
    for f in filters:
        assert re.search(r"\bI=-14\b", f), \
            f"encode loudnorm must target I=-14 (band center [-15,-13]), got: {f}"


def test_encode_loudnorm_lra_11():
    filters = _encode_loudnorm_filters((ROOT / "pipeline_v2.py").read_text())
    for f in filters:
        assert re.search(r"\bLRA=11\b", f), \
            f"encode loudnorm must specify LRA=11, got: {f}"


def test_encode_loudnorm_tp_minus_1_5():
    """T-11 spec: tighten true-peak ceiling from TP=-1 to TP=-1.5."""
    filters = _encode_loudnorm_filters((ROOT / "pipeline_v2.py").read_text())
    for f in filters:
        assert re.search(r"\bTP=-1\.5\b", f), \
            f"encode loudnorm must use TP=-1.5 (T-11 change), got: {f}"


# ---------- (b) end-to-end smoke: rendered audio measures in band ----------

SOURCE = ROOT / "source"
EVAL_VODS = [SOURCE / "vod-tyler1-jynxzi.mp4", SOURCE / "vod-medium.mp4"]


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1",
    reason="set RUN_SMOKE=1 to run the loudness re-encode oracle",
)
@pytest.mark.parametrize("vod", EVAL_VODS, ids=lambda p: p.name)
def test_smoke_re_encoded_clip_loudness_in_band(tmp_path, vod):
    """Render a 30s clip with the production encode pipeline; measure
    loudnorm_i via grade_metrics; must land inside the [-15, -13] band
    that T-08 grader enforces. This is the falsifiable oracle for T-11 —
    if delivered audio still measures < -15 LUFS, the fix didn't take."""
    if not vod.exists():
        pytest.skip(f"{vod.name} not present in source/")
    outdir = tmp_path / vod.stem
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(vod), str(outdir),
         "--clip-start", "120.0", "--clip-end", "150.0",
         "--subs-mode", "line", "--overlay", "off"],
        check=True,
    )
    out = outdir / "smoke.mp4"
    assert out.exists(), f"render produced no mp4 for {vod.name}"

    metrics = v2.grade_metrics(out)
    i = metrics.get("loudnorm_i")
    assert i is not None, "grade_metrics did not report loudnorm_i"
    assert -15.0 <= i <= -13.0, \
        f"{vod.name}: delivered audio loudness I={i:.2f} LUFS outside " \
        "[-15, -13] band — encode loudnorm did not normalize to target"


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1",
    reason="set RUN_SMOKE=1",
)
def test_smoke_full_pipeline_no_loudnorm_rejections_on_tyler1(tmp_path):
    """End-to-end falsifiable: re-run full pipeline on tyler1 with --n=3,
    confirm at least 3 shorts in the output dir survive grading without
    being rejected on loudnorm. Mirrors the M1 acceptance criterion."""
    if not EVAL_VODS[0].exists():
        pytest.skip("tyler1 vod not present")
    outdir = tmp_path / "tyler1-v2"
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(EVAL_VODS[0]), str(outdir),
         "--n", "3"],
        check=True,
    )
    sidecar = outdir / "shorts.json"
    assert sidecar.exists()
    shorts = json.loads(sidecar.read_text())["shorts"]

    # For each delivered short, locate its verdict.json and confirm it is not
    # rejected on loudnorm.
    survivors = 0
    rejected_on_loudnorm = []
    for s in shorts:
        f = ROOT / s["file"]
        verdict_path = f.with_suffix(".verdict.json")
        # If verdict not next to mp4, search rejected/ subdirs
        if not verdict_path.exists():
            rejected_dir = f.parent / "rejected" / "loudnorm"
            verdict_path = rejected_dir / verdict_path.name
        if not verdict_path.exists():
            continue
        v = json.loads(verdict_path.read_text())
        if v.get("rejected"):
            if "loudnorm" in v.get("hard_fails", []):
                rejected_on_loudnorm.append(s["file"])
        else:
            survivors += 1

    assert not rejected_on_loudnorm, \
        f"shorts still rejected on loudnorm after T-11 fix: {rejected_on_loudnorm}"
    assert survivors >= 3, \
        f"only {survivors} shorts survived grading on tyler1 — M1 needs ≥3"
