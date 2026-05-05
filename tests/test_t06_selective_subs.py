"""T-06 contract tests: selective subtitles burned only on engaging spans.

Local signal tagger (RMS z>1.5 OR HOOK_WORDS interjection OR scene cut ≤1s)
proposes candidates; judge crew vetoes via Y/N over tmux (JUDGE_STUB seam in
tests); renderer burns ASS dialogue only inside engaging=true spans.
--subs-mode default flips from 'line' (T-05) to 'selective' (T-06).
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline_v2 as v2


# ---------- (a) CLI default flips to selective ----------

def test_subs_mode_default_is_selective():
    src = (ROOT / "pipeline_v2.py").read_text()
    assert re.search(r"--subs-mode[\s\S]*?default\s*=\s*['\"]selective['\"]", src), \
        "--subs-mode default must flip to 'selective' in T-06"


def test_subs_mode_choices_include_selective():
    r = subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), "--help"],
        capture_output=True, text=True,
    )
    assert "selective" in r.stdout, "--subs-mode must offer 'selective' as a choice"
    # Existing choices must remain
    assert "line" in r.stdout and "word" in r.stdout, \
        "T-06 must not drop existing line/word modes"


# ---------- (b) local-signal candidate tagger ----------

def test_tag_candidate_spans_function_exists():
    assert callable(getattr(v2, "tag_candidate_spans", None)), \
        "pipeline_v2.tag_candidate_spans(segs, rms, scene_cuts, cs, ce) -> list is missing"


def _flat_rms(n=30):
    """Flat RMS that yields z≈0 across a window."""
    return np.full(n, 0.05)


def test_tag_fires_on_rms_peak():
    rms = _flat_rms(30)
    rms[10] = 5.0  # huge spike → z >> 1.5
    spans = v2.tag_candidate_spans([], rms, [], 0.0, 30.0)
    assert spans, "no spans returned despite a clear RMS peak"
    assert any(s["start"] <= 10.0 <= s["end"] for s in spans), \
        f"no span overlaps the RMS peak at t=10s: {spans}"
    assert any("rms" in s.get("reason", "").lower() for s in spans), \
        f"RMS-peak span missing 'rms' reason tag: {spans}"


def test_tag_fires_on_hook_word():
    segs = [{"start": 5.0, "end": 6.5, "text": "wait what is happening"}]
    spans = v2.tag_candidate_spans(segs, _flat_rms(30), [], 0.0, 30.0)
    assert any(s["start"] <= 5.5 <= s["end"] for s in spans), \
        f"no span overlaps the hook-word seg at t≈5.5s: {spans}"
    assert any("hook" in s.get("reason", "").lower() for s in spans), \
        f"hook-word span missing 'hook' reason tag: {spans}"


def test_tag_fires_on_scene_cut():
    spans = v2.tag_candidate_spans([], _flat_rms(30), [12.0], 0.0, 30.0)
    assert any(s["start"] <= 12.0 <= s["end"] for s in spans), \
        f"no span overlaps the scene cut at t=12s: {spans}"
    # Spec: scene cut taggs ±1s window
    cut_spans = [s for s in spans if s["start"] <= 12.0 <= s["end"]]
    assert any((s["end"] - s["start"]) <= 2.5 for s in cut_spans), \
        f"scene-cut span wider than expected ±1s window: {cut_spans}"
    assert any("scene" in s.get("reason", "").lower() or "cut" in s.get("reason", "").lower()
               for s in spans), \
        f"scene-cut span missing 'scene'/'cut' reason tag: {spans}"


def test_tag_returns_empty_when_no_signal():
    spans = v2.tag_candidate_spans(
        [{"start": 0.0, "end": 10.0, "text": "and then we walked over there"}],
        _flat_rms(30), [], 0.0, 30.0,
    )
    assert spans == [] or all(False for _ in spans), \
        f"tagger fired on flat audio + neutral text + no cuts: {spans}"


# ---------- (c) judge wrapper with stub seam ----------

def test_judge_span_function_exists():
    assert callable(getattr(v2, "judge_span", None)), \
        "pipeline_v2.judge_span(text, features) -> bool is missing"


def test_judge_span_honors_stub_yes(monkeypatch):
    monkeypatch.setenv("JUDGE_STUB", "Y")
    assert v2.judge_span("anything", {}) is True


def test_judge_span_honors_stub_no(monkeypatch):
    monkeypatch.setenv("JUDGE_STUB", "N")
    assert v2.judge_span("anything", {}) is False


def test_judge_span_consumes_sequence(monkeypatch):
    """Comma-separated JUDGE_STUB consumed in order across calls."""
    monkeypatch.setenv("JUDGE_STUB", "Y,N,Y")
    results = [v2.judge_span(f"text{i}", {}) for i in range(3)]
    assert results == [True, False, True], \
        f"judge stub sequence mismatch: {results}"


# ---------- (d) selection combines tag + judge ----------

def test_select_engaging_spans_function_exists():
    assert callable(getattr(v2, "select_engaging_spans", None)), \
        "pipeline_v2.select_engaging_spans(segs, rms, scene_cuts, cs, ce) -> list is missing"


def test_select_engaging_spans_filters_by_judge(monkeypatch):
    """Two candidate spans; judge stubbed Y,N → only one engaging=True."""
    monkeypatch.setenv("JUDGE_STUB", "Y,N")
    rms = _flat_rms(30)
    rms[5] = 5.0
    rms[20] = 5.0
    spans = v2.select_engaging_spans([], rms, [], 0.0, 30.0)
    engaging = [s for s in spans if s.get("engaging")]
    not_engaging = [s for s in spans if not s.get("engaging")]
    assert len(engaging) == 1, \
        f"expected exactly 1 engaging span (judge=Y), got {len(engaging)}: {spans}"
    assert len(not_engaging) >= 1, \
        f"expected ≥1 vetoed span (judge=N): {spans}"


# ---------- (e) selective ASS writer ----------

def test_write_ass_selective_function_exists():
    assert callable(getattr(v2, "write_ass_selective", None)), \
        "pipeline_v2.write_ass_selective(segs, engaging_spans, path) is missing"


def test_write_ass_selective_skips_non_engaging(tmp_path):
    """Segments outside any engaging span must NOT appear in the ASS dialogue."""
    segs = [
        {"start": 0.0, "end": 2.0, "text": "boring intro"},
        {"start": 11.0, "end": 12.0, "text": "exciting moment"},
        {"start": 20.0, "end": 22.0, "text": "boring outro"},
    ]
    engaging_spans = [{"start": 10.0, "end": 15.0, "engaging": True, "reason": "rms_peak"}]
    out = tmp_path / "sel.ass"
    v2.write_ass_selective(segs, engaging_spans, out)
    text = out.read_text()
    assert "exciting moment" in text, "engaging-overlap seg not burned"
    assert "boring intro" not in text, \
        "non-engaging intro seg leaked into ASS"
    assert "boring outro" not in text, \
        "non-engaging outro seg leaked into ASS"


def test_write_ass_selective_no_engaging_means_no_dialogue(tmp_path):
    """If no engaging span fires, ASS has no Dialogue lines (just header)."""
    segs = [{"start": 0.0, "end": 30.0, "text": "all neutral"}]
    out = tmp_path / "empty.ass"
    v2.write_ass_selective(segs, [], out)
    text = out.read_text()
    assert "Dialogue:" not in text, \
        "selective mode burned dialogue when no engaging span existed"


def test_write_ass_selective_preserves_locked_style(tmp_path):
    """Style stays Helvetica 72pt MarginV=544 (T-05 lock)."""
    out = tmp_path / "sel.ass"
    v2.write_ass_selective(
        [{"start": 1.0, "end": 2.0, "text": "hi"}],
        [{"start": 0.0, "end": 5.0, "engaging": True, "reason": "rms_peak"}],
        out,
    )
    text = out.read_text()
    assert re.search(r"Style:\s*Default,Helvetica,72,", text), \
        "Style must remain Helvetica 72pt"
    assert "544" in text, "MarginV=544 must remain"


# ---------- (f) wire-up ----------

def test_main_threads_selective_mode():
    src = (ROOT / "pipeline_v2.py").read_text()
    assert "select_engaging_spans" in src, \
        "main never calls select_engaging_spans for selective mode"
    assert "write_ass_selective" in src, \
        "main/render never calls write_ass_selective"


def test_render_one_dispatches_on_selective():
    """render_one must branch on subs_mode=='selective'."""
    src = (ROOT / "pipeline_v2.py").read_text()
    # Some explicit branch on the literal "selective"
    assert "\"selective\"" in src or "'selective'" in src, \
        "no literal 'selective' branch found in pipeline_v2.py"


# ---------- (g) smoke: vod-podcast selective render shows gaps ----------

PODCAST = ROOT / "source" / "vod-podcast.mp4"


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1" or not PODCAST.exists(),
    reason="set RUN_SMOKE=1 and ensure source/vod-podcast.mp4 is present",
)
def test_smoke_podcast_selective_has_gaps(tmp_path):
    """Render a 60s podcast clip in selective mode; the engaging-spans sidecar
    must show coverage < 100% (visible non-subtitled stretches between
    engaging spans), and each engaging span's reason must come from the
    documented set."""
    outdir = tmp_path / "podcast-selective"
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(PODCAST), str(outdir),
         "--clip-start", "60.0", "--clip-end", "120.0",
         "--subs-mode", "selective"],
        check=True,
    )
    out = outdir / "smoke.mp4"
    assert out.exists() and out.stat().st_size > 100_000, \
        "selective render did not produce a viable mp4"

    sidecar = outdir / "smoke.subtitle_spans.json"
    assert sidecar.exists(), \
        "selective mode must emit <stem>.subtitle_spans.json describing engaging spans"

    data = json.loads(sidecar.read_text())
    spans = data["spans"] if isinstance(data, dict) else data
    engaging = [s for s in spans if s.get("engaging")]

    assert len(engaging) >= 1, \
        f"no engaging spans flagged in 60s podcast clip: {spans}"

    clip_dur = 60.0
    coverage = sum(s["end"] - s["start"] for s in engaging)
    assert coverage < clip_dur, \
        f"engaging spans cover entire clip ({coverage}/{clip_dur}s) — " \
        "selective mode is not actually selective"
    assert coverage / clip_dur < 0.85, \
        f"engaging spans cover {coverage/clip_dur:.0%} of clip — " \
        "no visible non-subtitled stretches"

    allowed_reasons = {"rms_peak", "hook_word", "scene_cut", "judge"}
    for s in engaging:
        reason = s.get("reason", "").lower()
        assert any(r in reason for r in allowed_reasons), \
            f"engaging span has undocumented reason {reason!r}: must contain one of {allowed_reasons}"


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1" or not PODCAST.exists(),
    reason="set RUN_SMOKE=1",
)
def test_smoke_line_mode_still_full_coverage(tmp_path):
    """Sanity: --subs-mode=line still burns subtitles across the full clip
    (no selective filtering when explicitly opted out)."""
    outdir = tmp_path / "podcast-line"
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(PODCAST), str(outdir),
         "--clip-start", "60.0", "--clip-end", "90.0",
         "--subs-mode", "line"],
        check=True,
    )
    sidecar = outdir / "smoke.subtitle_spans.json"
    if sidecar.exists():
        data = json.loads(sidecar.read_text())
        spans = data.get("spans") if isinstance(data, dict) else data
        # In line mode, either no sidecar OR all-engaging coverage near 100%.
        engaging = [s for s in (spans or []) if s.get("engaging")]
        if engaging:
            coverage = sum(s["end"] - s["start"] for s in engaging)
            assert coverage / 30.0 > 0.85, \
                "line mode dropped coverage — selective filtering leaked"
