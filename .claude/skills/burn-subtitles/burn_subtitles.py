#!/usr/bin/env python3
# render a transparent subtitle PNG sequence from a transcribe-skill transcript.json
# (this ffmpeg build lacks libass/drawtext, so subtitles are composited as an overlay)
import json, math, os, struct, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

src_data = sys.argv[1]       # transcript.json OR chunks.json (style decides)
seqdir = sys.argv[2]
W = int(sys.argv[3])
H = int(sys.argv[4])
fps = float(sys.argv[5])
nframes = int(sys.argv[6])
style = sys.argv[7] if len(sys.argv) > 7 else "chunks"
fs = int(sys.argv[8]) if len(sys.argv) > 8 else 72
video = sys.argv[9] if len(sys.argv) > 9 else None

FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"
WHITE = (245, 245, 240, 255)
ACCENT = (0, 229, 255, 255)   # electric cyan — deliberate brand accent
STROKE = (0, 0, 0, 255)

# rolling-window tuning (legacy word-karaoke style only)
WINDOW = 4
PAUSE_GAP = 0.6
SLIDE_IN = 0.08
SLIDE_PX = 8

font = ImageFont.truetype(FONT, fs)
stroke = max(3, fs // 10)
maxw = W - int(W * 0.12)
lineh = int(fs * 1.25)
marginv = max(40, int(H * 0.22))


def rms_hot(path):
    sr = 8000
    p = subprocess.Popen(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-i", path, "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        stdout=subprocess.PIPE)
    r = []
    while True:
        chunk = p.stdout.read(sr * 2)
        if not chunk:
            break
        n = len(chunk) // 2
        sm = struct.unpack(f"<{n}h", chunk[: n * 2])
        if sm:
            r.append(math.sqrt(sum(x * x for x in sm) / n) / 32768.0)
    p.wait()
    if not r:
        return set()
    mean = sum(r) / len(r)
    sd = (sum((x - mean) ** 2 for x in r) / len(r)) ** 0.5 or 1e-9
    return {i for i, x in enumerate(r) if (x - mean) / sd > 1.0}


def wrap(tokens):
    space = font.getlength(" ")
    lines, cur, curw = [], [], 0.0
    for tok in tokens:
        tw = font.getlength(tok[0])
        add = tw if not cur else curw + space + tw
        if cur and add > maxw:
            lines.append(cur)
            cur, curw = [tok], tw
        else:
            cur.append(tok)
            curw = add
    if cur:
        lines.append(cur)
    return lines


cache = {}


def render(tokens):
    key = tokens
    if key in cache:
        return cache[key]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if tokens:
        d = ImageDraw.Draw(img)
        space = font.getlength(" ")
        lines = wrap(tokens)
        y = marginv
        for ln in lines:
            lw = sum(font.getlength(t[0]) for t in ln) + space * (len(ln) - 1)
            x = (W - lw) / 2
            for text, color, yoff in ln:
                bw = font.getlength(text)
                d.text((x, y + yoff), text, font=font, fill=color,
                       stroke_width=stroke, stroke_fill=STROKE)
                x += bw + space
            y += lineh
    path = os.path.join(seqdir, f"_state{len(cache):04d}.png")
    img.save(path)
    cache[key] = path
    return path


states = [() for _ in range(nframes)]

if style == "chunks":
    # Phrase-chunk rendering. The whole chunk shows for its [t0, t1] window;
    # the currently-spoken word is cyan, the rest are white. Chunks hard-cut.
    doc = json.load(open(src_data))
    chunks = doc.get("chunks", [])
    for fi in range(nframes):
        t = fi / fps
        active = None
        for c in chunks:
            if c["t0"] <= t < c["t1"]:
                active = c
                break
        # also show chunk just after its end for a small tail so the last word
        # doesn't vanish the instant it's spoken
        if active is None:
            for c in chunks:
                if c["t1"] <= t <= c["t1"] + 0.25:
                    active = c
                    break
        if active is None:
            continue
        toks = []
        for w in active["words"]:
            color = ACCENT if (w["t0"] <= t <= w["t1"]) else WHITE
            toks.append((str(w["w"]).strip(), color, 0))
        states[fi] = tuple(toks)
elif style == "word-karaoke":
    tr = json.load(open(src_data))
    words = [w for w in tr.get("words", []) if str(w.get("w", "")).strip()]
    spans = []
    for i, w in enumerate(words):
        vis_in = w["t0"]
        bump = words[i + WINDOW]["t0"] if i + WINDOW < len(words) else None
        gap_exit = None
        for j in range(i, len(words) - 1):
            if words[j + 1]["t0"] - words[j]["t1"] > PAUSE_GAP:
                gap_exit = words[j]["t1"] + 0.15
                break
        if gap_exit is None and bump is None:
            gap_exit = words[-1]["t1"] + 0.30
        vis_out = min(x for x in (bump, gap_exit) if x is not None)
        spans.append((vis_in, vis_out))
    for fi in range(nframes):
        t = fi / fps
        toks = []
        for wi, w in enumerate(words):
            vis_in, vis_out = spans[wi]
            if t < vis_in or t >= vis_out:
                continue
            if t < vis_in + SLIDE_IN:
                p = (t - vis_in) / SLIDE_IN
                yoff = int(round(SLIDE_PX * (1.0 - p)))
            else:
                yoff = 0
            color = ACCENT if w["t0"] <= t <= w["t1"] else WHITE
            toks.append((str(w["w"]).strip(), color, yoff))
        states[fi] = tuple(toks)
else:
    tr = json.load(open(src_data))
    segments = [s for s in tr.get("segments", []) if str(s.get("text", "")).strip()]
    keep = segments
    if style == "selective" and video:
        hot = rms_hot(video)
        flagged = [s for s in segments
                   if any(k in hot for k in range(int(s["t0"]), int(s["t1"]) + 1))]
        if flagged:
            keep = flagged
        else:
            print("burn-subtitles: selective found no hot spans, burning all",
                  file=sys.stderr)
    for s in keep:
        for fi in range(nframes):
            t = fi / fps
            if s["t0"] <= t <= s["t1"] + 0.25:
                states[fi] = tuple((tok, WHITE, 0) for tok in str(s["text"]).split())

shown = 0
for fi in range(nframes):
    src = render(states[fi])
    if states[fi]:
        shown += 1
    dst = os.path.join(seqdir, f"{fi + 1:06d}.png")
    if os.path.exists(dst):
        os.remove(dst)
    os.link(src, dst)

print(f"burn-subtitles: rendered {nframes} frames, {shown} with text, "
      f"{len(cache)} unique states, style={style}", file=sys.stderr)
if shown == 0:
    sys.exit(1)
