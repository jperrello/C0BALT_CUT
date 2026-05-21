#!/usr/bin/env python3
# render a transparent subtitle PNG sequence from a transcribe-skill transcript.json
# (this ffmpeg build lacks libass/drawtext, so subtitles are composited as an overlay)
import json, math, os, struct, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

transcript = sys.argv[1]
seqdir = sys.argv[2]
W = int(sys.argv[3])
H = int(sys.argv[4])
fps = float(sys.argv[5])
nframes = int(sys.argv[6])
style = sys.argv[7] if len(sys.argv) > 7 else "word-karaoke"
fs = int(sys.argv[8]) if len(sys.argv) > 8 else 72
video = sys.argv[9] if len(sys.argv) > 9 else None

FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
WHITE = (255, 255, 255, 255)
ACCENT = (255, 214, 51, 255)
STROKE = (0, 0, 0, 255)

with open(transcript) as f:
    tr = json.load(f)
words = [w for w in tr.get("words", []) if str(w.get("w", "")).strip()]
segments = [s for s in tr.get("segments", []) if str(s.get("text", "")).strip()]

font = ImageFont.truetype(FONT, fs)
stroke = max(2, fs // 14)
maxw = W - int(W * 0.12)
lineh = int(fs * 1.25)
marginv = max(40, int(H * 0.16))


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


# tokens: list of (text, color). renders one cached PNG per distinct state.
cache = {}


def render(tokens):
    key = tuple(tokens)
    if key in cache:
        return cache[key]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if tokens:
        d = ImageDraw.Draw(img)
        space = font.getlength(" ")
        lines = wrap(tokens)
        total_h = len(lines) * lineh
        y = H - marginv - total_h
        for ln in lines:
            lw = sum(font.getlength(t[0]) for t in ln) + space * (len(ln) - 1)
            x = (W - lw) / 2
            for text, color in ln:
                d.text((x, y), text, font=font, fill=color,
                       stroke_width=stroke, stroke_fill=STROKE)
                x += font.getlength(text) + space
            y += lineh
    path = os.path.join(seqdir, f"_state{len(cache):04d}.png")
    img.save(path)
    cache[key] = path
    return path


# build a per-frame state list
states = [() for _ in range(nframes)]

if style == "word-karaoke" and words:
    groups, cur = [], [words[0]]
    for w in words[1:]:
        if w["t0"] - cur[-1]["t1"] > 0.6 or len(cur) >= 6:
            groups.append(cur)
            cur = [w]
        else:
            cur.append(w)
    groups.append(cur)
    for g in groups:
        g0, g1 = g[0]["t0"], g[-1]["t1"]
        for i in range(nframes):
            t = i / fps
            if not (g0 <= t <= g1 + 0.25):
                continue
            active = 0
            for j, w in enumerate(g):
                if t >= w["t0"]:
                    active = j
            states[i] = tuple(
                (str(w["w"]).strip(), ACCENT if j == active else WHITE)
                for j, w in enumerate(g))
else:
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
        for i in range(nframes):
            t = i / fps
            if s["t0"] <= t <= s["t1"] + 0.25:
                states[i] = tuple((tok, WHITE) for tok in str(s["text"]).split())

# write the numbered frame sequence (hardlink duplicates for speed)
shown = 0
for i in range(nframes):
    src = render(states[i])
    if states[i]:
        shown += 1
    dst = os.path.join(seqdir, f"{i + 1:06d}.png")
    if os.path.exists(dst):
        os.remove(dst)
    os.link(src, dst)

print(f"burn-subtitles: rendered {nframes} frames, {shown} with text, "
      f"{len(cache)} unique states, style={style}", file=sys.stderr)
if shown == 0:
    sys.exit(1)
