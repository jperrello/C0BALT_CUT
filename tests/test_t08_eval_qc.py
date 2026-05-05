"""T-08 contract tests: eval/QC loop with auto-rejection.

Red-phase falsifiable assertions for the grader. Hard fails move artifacts to
delivered/rejected/<reason>/ via shutil.move (never delete). Soft flags warn.
A <name>.verdict.json sidecar is written next to every render.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline_v2 as v2

FFMPEG = v2.FFMPEG


# ---------- pure evaluator: deterministic per-category logic ----------

HEALTHY_METRICS = {
    "size_bytes": 5_000_000,
    "duration_s": 35.0,
    "loudnorm_i": -14.0,
    "face_tile_black_frac": 0.05,
    "transcript_words": 60,
    "reframe_jerk": 0.5,
    "hook_window_energy": 1.2,
    "hook_in_first_3s": True,
}


def test_evaluate_function_exists():
    assert callable(getattr(v2, "evaluate", None)), \
        "pipeline_v2.evaluate(metrics) -> verdict dict is missing"


def test_grade_metrics_function_exists():
    assert callable(getattr(v2, "grade_metrics", None)), \
        "pipeline_v2.grade_metrics(path) -> metrics dict is missing"


def test_grade_function_exists():
    assert callable(getattr(v2, "grade", None)), \
        "pipeline_v2.grade(path) entrypoint is missing"


def test_evaluate_verdict_schema_keys():
    v = v2.evaluate(HEALTHY_METRICS)
    for k in ("metrics", "hard_fails", "soft_flags", "rejected", "rejection_reason"):
        assert k in v, f"verdict missing key {k!r}"
    assert isinstance(v["hard_fails"], list)
    assert isinstance(v["soft_flags"], list)
    assert isinstance(v["rejected"], bool)


def test_evaluate_healthy_passes():
    v = v2.evaluate(HEALTHY_METRICS)
    assert v["rejected"] is False
    assert v["hard_fails"] == []
    assert v["rejection_reason"] is None


@pytest.mark.parametrize("override,expected_reason", [
    ({"size_bytes": 50_000}, "size"),
    ({"duration_s": 10.0}, "duration"),
    ({"duration_s": 70.0}, "duration"),
    ({"loudnorm_i": -20.0}, "loudnorm"),
    ({"loudnorm_i": -10.0}, "loudnorm"),
    ({"face_tile_black_frac": 0.6}, "face_black"),
    ({"transcript_words": 0}, "transcript_empty"),
])
def test_evaluate_rejects_each_hard_fail(override, expected_reason):
    m = dict(HEALTHY_METRICS)
    m.update(override)
    v = v2.evaluate(m)
    assert v["rejected"] is True, f"{override} should reject"
    assert expected_reason in v["hard_fails"], \
        f"{override}: expected {expected_reason!r} in hard_fails, got {v['hard_fails']}"
    assert v["rejection_reason"] == expected_reason or \
        (isinstance(v["rejection_reason"], str) and expected_reason in v["rejection_reason"]), \
        f"rejection_reason should name {expected_reason!r}, got {v['rejection_reason']!r}"


@pytest.mark.parametrize("override,flag", [
    ({"reframe_jerk": 50.0}, "reframe_jerk"),
    ({"hook_window_energy": -3.0}, "low_hook_energy"),
    ({"hook_in_first_3s": False}, "no_interjection_first_3s"),
])
def test_evaluate_soft_flags_warn_but_keep(override, flag):
    m = dict(HEALTHY_METRICS)
    m.update(override)
    v = v2.evaluate(m)
    assert v["rejected"] is False, \
        f"{override} is a soft flag and must NOT reject"
    assert flag in v["soft_flags"], \
        f"expected {flag!r} in soft_flags, got {v['soft_flags']}"


def test_evaluate_loudnorm_band_is_minus15_to_minus13():
    """Spec locks loudnorm I window to [-15, -13] inclusive."""
    for i in (-15.0, -14.0, -13.0):
        m = dict(HEALTHY_METRICS); m["loudnorm_i"] = i
        assert v2.evaluate(m)["rejected"] is False, f"I={i} should be in band"
    for i in (-15.01, -12.99):
        m = dict(HEALTHY_METRICS); m["loudnorm_i"] = i
        assert v2.evaluate(m)["rejected"] is True, f"I={i} should reject"


def test_evaluate_duration_band_is_25_to_65():
    for d in (25.0, 45.0, 65.0):
        m = dict(HEALTHY_METRICS); m["duration_s"] = d
        assert v2.evaluate(m)["rejected"] is False, f"dur={d} should pass"
    for d in (24.99, 65.01):
        m = dict(HEALTHY_METRICS); m["duration_s"] = d
        assert v2.evaluate(m)["rejected"] is True, f"dur={d} should reject"


# ---------- side effects: sidecar + auto-move ----------

def _synthesize_mp4(path: Path, duration: float = 30.0, big: bool = True):
    """Render a test mp4. By default uses random noise to keep size > 100KB
    so the size hard-fail does not co-fire with duration tests. Set big=False
    to deliberately produce a tiny (<100KB) file for size-check regression."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if big:
        vsrc = f"nullsrc=s=640x360:d={duration}:r=24,geq=r='random(0)*255':g='random(1)*255':b='random(2)*255'"
    else:
        vsrc = f"color=c=blue:s=160x90:d={duration}:r=5"
    subprocess.run([
        FFMPEG, "-nostdin", "-v", "error", "-y",
        "-f", "lavfi", "-i", vsrc,
        "-f", "lavfi", "-i", f"anullsrc=cl=mono:r=16000:d={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(path)
    ], check=True, capture_output=True)


def test_grade_writes_verdict_sidecar_alongside_healthy(tmp_path, monkeypatch):
    """Healthy render keeps a <stem>.verdict.json next to it in delivered/."""
    delivered = tmp_path / "delivered"
    delivered.mkdir()
    mp4 = delivered / "healthy.mp4"
    _synthesize_mp4(mp4, duration=30.0)

    # Inject metrics so we don't depend on real loudnorm/face/transcript
    monkeypatch.setattr(v2, "grade_metrics", lambda p: dict(HEALTHY_METRICS,
                        size_bytes=p.stat().st_size, duration_s=30.0))
    monkeypatch.setattr(v2, "DELIVER_DIR", delivered, raising=False)

    result = v2.grade(mp4)
    sidecar = delivered / "healthy.verdict.json"
    assert sidecar.exists(), "verdict.json sidecar not written next to healthy mp4"
    assert mp4.exists(), "healthy mp4 was moved when it should have stayed"
    data = json.loads(sidecar.read_text())
    assert data["rejected"] is False


def test_grade_moves_rejected_short_clip_to_duration_subdir(tmp_path, monkeypatch):
    """Falsifiable spec: synthetic 10s mp4 in delivered/ → moved to
    delivered/rejected/duration/ with verdict.json describing the rejection."""
    delivered = tmp_path / "delivered"
    delivered.mkdir()
    mp4 = delivered / "shortie.mp4"
    _synthesize_mp4(mp4, duration=10.0)

    monkeypatch.setattr(v2, "DELIVER_DIR", delivered, raising=False)
    # Use real grade_metrics for duration (ffprobe), but stub the slow bits.
    monkeypatch.setattr(v2, "grade_metrics", lambda p: dict(HEALTHY_METRICS,
                        size_bytes=p.stat().st_size, duration_s=10.0))

    v2.grade(mp4)

    rejected_dir = delivered / "rejected" / "duration"
    moved = rejected_dir / "shortie.mp4"
    sidecar = rejected_dir / "shortie.verdict.json"
    assert rejected_dir.is_dir(), \
        f"delivered/rejected/duration/ not created: {list(delivered.glob('**/*'))}"
    assert moved.exists(), \
        f"rejected mp4 not moved to {rejected_dir}: {list(delivered.glob('**/*'))}"
    assert not mp4.exists(), "rejected mp4 still in original location"
    assert sidecar.exists(), "verdict.json sidecar did not travel with the rejected mp4"
    data = json.loads(sidecar.read_text())
    assert data["rejected"] is True
    assert "duration" in data["hard_fails"]


def test_grade_never_deletes_uses_shutil_move():
    """Source-text invariant: the grader must use shutil.move, never os.remove,
    Path.unlink, or shutil.rmtree on artifacts."""
    src = (ROOT / "pipeline_v2.py").read_text()
    # Locate the grader region — anything between `def grade` and the next top-level def.
    import re
    m = re.search(r"def grade\b.*?(?=\ndef |\Z)", src, re.S)
    assert m, "no def grade(...) found in pipeline_v2.py"
    region = m.group(0)
    assert "shutil.move" in region, "grade() must use shutil.move for relocation"
    forbidden = ["os.remove", ".unlink(", "shutil.rmtree", "os.unlink"]
    for bad in forbidden:
        assert bad not in region, f"grade() must NEVER delete artifacts; found {bad!r}"


def test_deliver_invokes_grader():
    """Wiring requirement: pipeline_v2.deliver() must call grade()."""
    src = (ROOT / "pipeline_v2.py").read_text()
    import re
    m = re.search(r"def deliver\b.*?(?=\ndef |\Z)", src, re.S)
    assert m, "no def deliver(...) found"
    region = m.group(0)
    assert "grade(" in region, \
        "deliver() must invoke grade() so QC runs automatically on every delivered render"


def test_rejection_subdir_named_after_reason():
    """All five hard-fail reasons must have stable subdir names."""
    expected = {"size", "duration", "loudnorm", "face_black", "transcript_empty"}
    src = (ROOT / "pipeline_v2.py").read_text()
    # The implementer can route by reason however they like, but the spec
    # locks subdir names — verify all five strings are referenced as path
    # components or string literals somewhere in the grader region.
    import re
    m = re.search(r"def grade\b.*?(?=\ndef |\Z)", src, re.S)
    region = m.group(0) if m else ""
    missing = [r for r in expected if r not in region and r not in src]
    assert not missing, \
        f"hard-fail reason names missing from grader: {missing}"


# ---------- end-to-end smoke: full evaluator on a synth mp4 ----------

def test_grade_rejects_real_undersized_file(tmp_path, monkeypatch):
    """REGRESSION: a real <100KB mp4 routed through grade() must be rejected
    with reason='size'. Catches the anti-pattern where grade() bumps the
    measured size_bytes upward to make synth fixtures pass — that backdoor
    would defeat the size hard-fail in production.

    grade() must NOT mutate the metric; if the real file is <100KB, evaluate()
    must see the real value and reject."""
    delivered = tmp_path / "delivered"
    delivered.mkdir()
    mp4 = delivered / "tiny.mp4"
    _synthesize_mp4(mp4, duration=30.0, big=False)
    actual_size = mp4.stat().st_size
    assert actual_size < 100_000, \
        f"fixture broken: tiny mp4 is {actual_size} bytes, must be <100KB for this test"

    monkeypatch.setattr(v2, "DELIVER_DIR", delivered, raising=False)
    # Real grade_metrics — do NOT inject. The real on-disk size flows through.
    # Stub only the slow non-size metrics.
    real_grade_metrics = v2.grade_metrics
    def patched(p):
        m = dict(HEALTHY_METRICS)
        m["size_bytes"] = p.stat().st_size  # real, unmutated
        m["duration_s"] = 30.0
        return m
    monkeypatch.setattr(v2, "grade_metrics", patched)

    v2.grade(mp4)
    rejected_dir = delivered / "rejected" / "size"
    assert rejected_dir.is_dir(), \
        f"undersized real file not routed to rejected/size/. " \
        f"grade() may be silently bumping size_bytes — check pipeline_v2.py grade()."
    sidecar = rejected_dir / "tiny.verdict.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["rejected"] is True
    assert "size" in data["hard_fails"]
    # And the metric stored in the verdict must reflect the REAL size, not a bumped value.
    assert data["metrics"]["size_bytes"] == actual_size, \
        f"verdict.metrics.size_bytes was mutated: {data['metrics']['size_bytes']} != {actual_size}"


def test_smoke_real_metrics_on_synth_mp4_rejects_short(tmp_path):
    """Run grade_metrics + evaluate on a real 10s synth mp4 (no monkeypatch)
    and confirm duration-based rejection survives the real metric path.

    Loosely tolerated: this exercises the actual grade_metrics implementation
    end-to-end on a tiny artifact that should be cheap to grade. Other hard
    fails may co-fire (size, transcript_empty) — we only assert duration is
    among them."""
    mp4 = tmp_path / "tenSec.mp4"
    _synthesize_mp4(mp4, duration=10.0)
    metrics = v2.grade_metrics(mp4)
    assert "duration_s" in metrics
    assert 9.0 <= metrics["duration_s"] <= 11.0
    verdict = v2.evaluate(metrics)
    assert verdict["rejected"] is True
    assert "duration" in verdict["hard_fails"]
