"""T-05 contract tests: word-level karaoke subtitles via whisperX phoneme alignment.

Red-phase falsifiable assertions for adding --subs-mode={line,word} to pipeline_v2.
Smoke gated behind RUN_SMOKE=1 (requires whisperx + model + the three eval VODs).
"""
import hashlib
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

def test_subs_mode_flag_exists_in_help():
    r = subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), "--help"],
        capture_output=True, text=True,
    )
    assert "--subs-mode" in r.stdout, "missing --subs-mode CLI flag"
    assert "line" in r.stdout and "word" in r.stdout, \
        "--subs-mode must offer choices line and word"


def test_subs_mode_default_is_line():
    """Default behavior must be unchanged: line mode."""
    import argparse
    # Reuse v2.main parser construction by invoking with minimal args
    r = subprocess.run(
        ["python3", "-c",
         "import sys; sys.path.insert(0, %r); "
         "from pipeline_v2 import main; "
         "import argparse, inspect; "
         "src = inspect.getsource(main); "
         "print('SUBS_DEFAULT_LINE' if 'default=\"line\"' in src or "
         "\"default='line'\" in src else 'NO')" % str(ROOT)],
        capture_output=True, text=True,
    )
    assert "SUBS_DEFAULT_LINE" in r.stdout, \
        "--subs-mode must default to 'line' (string literal in main())"


# ---------- (b) word-mode ASS writer ----------

def test_write_ass_word_function_exists():
    assert callable(getattr(v2, "write_ass_word", None)), \
        "pipeline_v2.write_ass_word(words, path) is missing"


def test_write_ass_word_emits_k_karaoke_tags(tmp_path):
    words = [
        {"start": 0.00, "end": 0.30, "word": "wait"},
        {"start": 0.30, "end": 0.55, "word": "what"},
        {"start": 0.55, "end": 0.90, "word": "is"},
        {"start": 0.90, "end": 1.40, "word": "happening"},
    ]
    out = tmp_path / "k.ass"
    v2.write_ass_word(words, out)
    text = out.read_text()
    assert text.count("\\k") >= len(words), \
        f"expected ≥{len(words)} \\k tags, got {text.count('\\\\k')}"
    # Each word must appear in the dialogue text
    for w in ("wait", "what", "is", "happening"):
        assert w in text, f"word {w!r} missing from ASS"


def test_write_ass_word_preserves_locked_style(tmp_path):
    """Style line must remain Helvetica 72pt MarginV=544 in word mode."""
    out = tmp_path / "k.ass"
    v2.write_ass_word(
        [{"start": 0.0, "end": 0.5, "word": "hello"}], out,
    )
    text = out.read_text()
    assert "Helvetica" in text, "locked font Helvetica missing"
    assert re.search(r"Style:\s*Default,Helvetica,72,", text), \
        "Style must be Helvetica 72pt"
    assert "544" in text, "locked MarginV=544 missing"


def test_write_ass_word_k_durations_match_word_lengths(tmp_path):
    """Sum of \\k centiseconds in a dialogue line ≈ dialogue duration in cs."""
    words = [
        {"start": 0.00, "end": 0.40, "word": "hey"},
        {"start": 0.40, "end": 0.80, "word": "you"},
    ]
    out = tmp_path / "k.ass"
    v2.write_ass_word(words, out)
    text = out.read_text()
    # Extract the centisecond values inside {\kNN} tags.
    ks = [int(x) for x in re.findall(r"\\k(\d+)", text)]
    assert ks, "no \\k centisecond values found"
    # Each word is 40cs (0.40s); both words → 80cs total.
    total_cs = sum(ks)
    assert 70 <= total_cs <= 90, \
        f"sum of \\k cs ({total_cs}) not within tolerance of word durations (~80cs)"


# ---------- (c) line mode unchanged ----------

def test_line_mode_write_ass_unchanged(tmp_path):
    """Existing write_ass output for a fixed input must remain byte-stable.

    Locks the line-mode burn against accidental regression while word mode is added.
    """
    segs = [
        {"start": 0.0, "end": 1.5, "text": "hello world"},
        {"start": 1.5, "end": 3.0, "text": "goodbye world"},
    ]
    out = tmp_path / "line.ass"
    v2.write_ass(segs, out)
    text = out.read_text()
    assert "Style: Default,Helvetica,72," in text
    assert "MarginV=544" in text or ",544,1" in text  # MarginV is the position before Encoding
    assert "Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,hello world" in text
    assert "Dialogue: 0,0:00:01.50,0:00:03.00,Default,,0,0,0,,goodbye world" in text


# ---------- (d) whisperX alignment wrapper ----------

def test_align_words_function_exists():
    """Wrapper that runs whisperX phoneme alignment over mlx-whisper line segs."""
    assert callable(getattr(v2, "align_words", None)), \
        "pipeline_v2.align_words(segs, audio_path) -> list[{start,end,word}] is missing"


# ---------- (e) render_one threads subs_mode ----------

def test_render_one_accepts_subs_mode():
    import inspect
    sig = inspect.signature(v2.render_one)
    assert "subs_mode" in sig.parameters, \
        "render_one must accept subs_mode parameter to dispatch line vs word burn"


def test_main_passes_subs_mode_to_render_one():
    src = (ROOT / "pipeline_v2.py").read_text()
    assert "subs_mode" in src, "subs_mode never threaded through main"
    # render_one calls in main must pass subs_mode (or args.subs_mode)
    assert re.search(r"render_one\([^)]*subs_mode", src) or \
           re.search(r"render_one\([^)]*args\.subs_mode", src), \
        "render_one is not called with subs_mode in main"


# ---------- smoke: word mode produces in-sync per-word highlight ----------

SOURCE = ROOT / "source"
TYLER1 = SOURCE / "vod-tyler1-jynxzi.mp4"
EVAL_VODS = [
    SOURCE / "vod-tyler1-jynxzi.mp4",
    SOURCE / "vod-medium.mp4",
    SOURCE / "vod-podcast.mp4",
]


def _frame_hash(mp4: Path, t: float, tmp: Path) -> str:
    f = tmp / f"frame_{int(t*1000)}.png"
    subprocess.run(
        [v2.FFMPEG, "-nostdin", "-v", "error", "-y",
         "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1", str(f)],
        check=True,
    )
    # Hash only the bottom subtitle band to isolate karaoke change
    # (full-frame hash would also change due to face/screen motion).
    import cv2
    img = cv2.imread(str(f))
    band = img[1500:1700, :, :]  # roughly the subtitle band at MarginV=544
    return hashlib.sha1(band.tobytes()).hexdigest()


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1" or not TYLER1.exists(),
    reason="set RUN_SMOKE=1 and ensure source/vod-tyler1-jynxzi.mp4 is present",
)
def test_smoke_word_mode_highlights_individual_words(tmp_path):
    """Render a 30s tyler1 clip in word mode; sample two frames straddling a
    known word boundary; the subtitle band's pixel hash must differ — proving
    the active word changed (karaoke highlight moved)."""
    outdir = tmp_path / "smoke"
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(TYLER1), str(outdir),
         "--clip-start", "120.0", "--clip-end", "150.0",
         "--subs-mode", "word"],
        check=True,
    )
    out_mp4 = outdir / "smoke.mp4"
    assert out_mp4.exists(), "word-mode render did not produce smoke.mp4"

    # words sidecar must accompany the render so we know where boundaries are
    words_json = outdir / "smoke.words.json"
    assert words_json.exists(), \
        "word mode must emit <out>.words.json with per-word timestamps"
    words = json.loads(words_json.read_text())
    assert len(words) >= 5, f"too few aligned words: {len(words)}"

    # Pick a word boundary somewhere in the clip
    boundary = words[2]["end"]  # end of the third word
    h_before = _frame_hash(out_mp4, max(0.0, boundary - 0.10), tmp_path)
    h_after = _frame_hash(out_mp4, boundary + 0.10, tmp_path)
    assert h_before != h_after, \
        f"subtitle band identical at {boundary-0.10:.2f}s and {boundary+0.10:.2f}s — " \
        "karaoke highlight not advancing between words"


@pytest.mark.skipif(
    os.environ.get("RUN_SMOKE") != "1",
    reason="set RUN_SMOKE=1; requires all three eval VODs in source/",
)
@pytest.mark.parametrize("vod", EVAL_VODS, ids=lambda p: p.name)
@pytest.mark.parametrize("mode", ["line", "word"])
def test_smoke_both_modes_succeed_on_each_vod(tmp_path, vod, mode):
    """Both --subs-mode=line and --subs-mode=word must produce a non-empty mp4
    on at least one clip from each of the three eval VODs."""
    if not vod.exists():
        pytest.skip(f"{vod.name} not yet downloaded")
    outdir = tmp_path / f"{vod.stem}-{mode}"
    subprocess.run(
        ["python3", str(ROOT / "pipeline_v2.py"), str(vod), str(outdir),
         "--clip-start", "60.0", "--clip-end", "90.0",
         "--subs-mode", mode],
        check=True,
    )
    out = outdir / "smoke.mp4"
    assert out.exists() and out.stat().st_size > 100_000, \
        f"{mode} mode produced empty/missing mp4 for {vod.name}"
