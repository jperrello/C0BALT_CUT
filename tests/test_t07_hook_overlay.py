"""T-07 contract tests: hook-overlay text rendering.

Red-phase falsifiable assertions. Adds --overlay={off,on} (default on),
a scribe-backed text generator, and a top-of-frame ASS overlay burn.
Smoke gated behind RUN_SMOKE=1.
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


# ---------- (a) CLI flag ----------

def test_overlay_flag_in_help():
    r = subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), "--help"],
        capture_output=True, text=True,
    )
    assert "--overlay" in r.stdout, "missing --overlay CLI flag"
    assert "on" in r.stdout and "off" in r.stdout, \
        "--overlay must offer choices on and off"


def test_overlay_default_is_on():
    src = (ROOT / "pipeline_v2.py").read_text()
    assert re.search(r"--overlay[\s\S]*?default\s*=\s*['\"]on['\"]", src), \
        "--overlay must default to 'on' (string literal in main())"


# ---------- (b) scribe-backed text generator ----------

def test_request_overlay_function_exists():
    assert callable(getattr(v2, "request_overlay", None)), \
        "pipeline_v2.request_overlay(transcript, features) -> str is missing"


def test_request_overlay_signature_takes_transcript_and_features():
    import inspect
    sig = inspect.signature(v2.request_overlay)
    params = list(sig.parameters)
    # Accept either positional or keyword names; require a 2-arg shape
    assert len(params) >= 2, \
        "request_overlay must take at least (transcript, features)"


def test_request_overlay_returns_5_to_7_words(monkeypatch):
    """Test seam: SCRIBE_STUB env var lets the test drive a deterministic
    response without invoking the live scribe tmux pane. Implementer must
    respect SCRIBE_STUB when set.

    Output must be 5–7 words (TikTok-grammar overlay line)."""
    monkeypatch.setenv("SCRIBE_STUB", "wait this guy actually pulled it off")
    out = v2.request_overlay(
        "okay so wait this guy actually pulled it off no way",
        {"hook_in_first_3s": True, "hook_score": 2.0,
         "standalone_3s": False, "duration_fit": 0.9},
    )
    assert isinstance(out, str) and out.strip(), \
        f"request_overlay must return non-empty str, got {out!r}"
    n = len(out.split())
    assert 5 <= n <= 7, f"overlay must be 5-7 words, got {n}: {out!r}"


def test_request_overlay_truncates_or_rejects_overlong_stub(monkeypatch):
    """If scribe returns >7 words, request_overlay must clamp to 5-7."""
    monkeypatch.setenv(
        "SCRIBE_STUB",
        "this is a much longer line than seven words could ever fit politely",
    )
    out = v2.request_overlay("transcript", {"hook_in_first_3s": True})
    n = len(out.split())
    assert 5 <= n <= 7, f"overlay must clamp to 5-7 words, got {n}: {out!r}"


# ---------- (c) ASS overlay writer (top-aligned) ----------

def test_write_ass_overlay_function_exists():
    assert callable(getattr(v2, "write_ass_overlay", None)), \
        "pipeline_v2.write_ass_overlay(text, start, end, path) is missing"


def test_write_ass_overlay_top_aligned(tmp_path):
    """Overlay must render at the TOP of the canvas — Alignment 8 (top-center)
    via either the Style line or an inline {\\an8} override on the dialogue."""
    out = tmp_path / "overlay.ass"
    v2.write_ass_overlay("wait this guy pulled it off", 0.0, 5.0, out)
    text = out.read_text()
    assert "wait this guy pulled it off" in text, \
        "overlay text missing from ASS"
    top_aligned = (
        re.search(r"Style:[^\n]*,\s*8\s*,\s*\d+,\s*\d+,\s*\d+,\s*\d?\s*$", text, re.M)
        is not None
        or "\\an8" in text
        or re.search(r"Alignment[^=]*=\s*8", text)
    )
    assert top_aligned, \
        "overlay must be top-aligned (Style Alignment=8 or \\an8 inline override)"


def test_write_ass_overlay_includes_timing(tmp_path):
    out = tmp_path / "overlay.ass"
    v2.write_ass_overlay("five word overlay line here", 1.5, 7.0, out)
    text = out.read_text()
    # ASS timestamps are H:MM:SS.cs
    assert "0:00:01.50" in text, "start time not encoded"
    assert "0:00:07.00" in text, "end time not encoded"


# ---------- (d) render_one + main wire-up ----------

def test_render_one_accepts_overlay_param():
    import inspect
    sig = inspect.signature(v2.render_one)
    has_overlay_param = any(
        "overlay" in name for name in sig.parameters
    )
    assert has_overlay_param, \
        "render_one must accept an overlay parameter (overlay/overlay_text/overlay_mode)"


def test_main_threads_overlay_flag():
    src = (ROOT / "pipeline_v2.py").read_text()
    assert "args.overlay" in src, \
        "main must read args.overlay and thread it into render_one"
    # render_one calls in main must reference overlay
    assert re.search(r"render_one\([^)]*overlay", src), \
        "render_one is not called with overlay in main"


def test_overlay_off_disables_burn():
    """Source-level check: there is a guard on overlay==off (or overlay is None)
    that skips the overlay burn."""
    src = (ROOT / "pipeline_v2.py").read_text()
    # Either a literal 'off' check or a truthiness gate.
    assert (
        re.search(r"overlay\s*==\s*['\"]off['\"]", src)
        or re.search(r"overlay\s*!=\s*['\"]off['\"]", src)
        or re.search(r"if\s+overlay\b[^:]*:", src)
    ), "no guard found that disables overlay burn when --overlay=off"


def test_ranker_invokes_request_overlay():
    """Per spec: 'For each shortlisted clip, ranker calls scribe ... to obtain
    a 5-7 word overlay line.' Wire-up check."""
    src = (ROOT / "pipeline_v2.py").read_text()
    assert "request_overlay(" in src, \
        "request_overlay never called from main/ranker shortlist loop"


# ---------- (e) smoke: three eval VODs each get a distinct legible overlay ----------

SOURCE = ROOT / "source"
EVAL_VODS = [
    SOURCE / "vod-tyler1-jynxzi.mp4",
    SOURCE / "vod-medium.mp4",
    SOURCE / "vod-podcast.mp4",
]


def _top_band_nonblack_frac(mp4: Path, t: float, tmp: Path) -> float:
    """Fraction of pixels in the top 200 rows that are NOT near-black.
    Proxy for 'overlay text is rendered'."""
    import cv2
    f = tmp / "frame.png"
    subprocess.run(
        [v2.FFMPEG, "-nostdin", "-v", "error", "-y",
         "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1", str(f)],
        check=True,
    )
    img = cv2.imread(str(f))
    band = img[0:200, :, :]
    luma = band.mean(axis=2)
    return float((luma > 200).mean())  # white-ish text pixels


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1",
    reason="set RUN_SMOKE=1; needs all three eval VODs in source/ + scribe live",
)
@pytest.mark.parametrize("vod", EVAL_VODS, ids=lambda p: p.name)
def test_smoke_overlay_renders_top_band_per_vod(tmp_path, vod):
    """For each eval VOD: render a 30s clip with --overlay=on and confirm the
    top band of the first frame contains bright (text-like) pixels above a
    minimum coverage threshold."""
    if not vod.exists():
        pytest.skip(f"{vod.name} not yet downloaded")
    outdir = tmp_path / vod.stem
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(vod), str(outdir),
         "--clip-start", "60.0", "--clip-end", "90.0",
         "--overlay", "on"],
        check=True,
    )
    out = outdir / "smoke.mp4"
    assert out.exists(), f"render produced no mp4 for {vod.name}"
    sidecar = outdir / "smoke.overlay.json"
    assert sidecar.exists(), \
        f"overlay sidecar <stem>.overlay.json must be written for {vod.name}"
    overlay_text = json.loads(sidecar.read_text()).get("text", "")
    assert 5 <= len(overlay_text.split()) <= 7, \
        f"overlay text must be 5-7 words, got {overlay_text!r}"
    frac = _top_band_nonblack_frac(out, 1.5, tmp_path)
    assert frac > 0.005, \
        f"top band has <0.5% bright pixels at t=1.5s on {vod.name} — overlay invisible"


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1",
    reason="set RUN_SMOKE=1; needs all three eval VODs",
)
def test_smoke_overlays_distinct_across_three_vods(tmp_path):
    """The three smoke overlays must be distinct strings — proves scribe is
    actually adapting to the clip, not emitting a constant placeholder."""
    texts = []
    for vod in EVAL_VODS:
        if not vod.exists():
            pytest.skip(f"{vod.name} not yet downloaded")
        outdir = tmp_path / vod.stem
        subprocess.run(
            ["python3", str(ROOT / "pipeline_v2.py"), str(vod), str(outdir),
             "--clip-start", "60.0", "--clip-end", "90.0",
             "--overlay", "on"],
            check=True,
        )
        sidecar = outdir / "smoke.overlay.json"
        texts.append(json.loads(sidecar.read_text())["text"])
    assert len(set(texts)) == 3, f"overlays not distinct across VODs: {texts}"


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1",
    reason="set RUN_SMOKE=1",
)
def test_smoke_overlay_off_yields_dark_top_band(tmp_path):
    """Sanity: --overlay=off must NOT burn an overlay; top band stays dark."""
    vod = EVAL_VODS[0]
    if not vod.exists():
        pytest.skip(f"{vod.name} not yet downloaded")
    outdir = tmp_path / "off"
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(vod), str(outdir),
         "--clip-start", "60.0", "--clip-end", "90.0",
         "--overlay", "off"],
        check=True,
    )
    out = outdir / "smoke.mp4"
    frac = _top_band_nonblack_frac(out, 1.5, tmp_path)
    assert frac < 0.005, \
        f"--overlay=off still produced bright top band ({frac:.3%}) — overlay leaked"
