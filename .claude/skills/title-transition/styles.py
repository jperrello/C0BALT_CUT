#!/usr/bin/env python3
# render a title style as a full-frame RGBA PNG sequence + events.json (SFX cue
# list). one style per invocation. optional 8th arg renders a corner label.png
# (demo use only — production passes no label).
# usage: styles.py <style> <title> <outdir> <W> <H> <dur> <fps> [label]
import json, math, os, random, sys
from PIL import Image, ImageDraw, ImageFont

style = "glitch"  # the only title animation — every short uses it
title = sys.argv[2].strip().upper()
outdir = sys.argv[3]
W, H = int(sys.argv[4]), int(sys.argv[5])
dur, fps = float(sys.argv[6]), int(sys.argv[7])
label = sys.argv[8] if len(sys.argv) > 8 else ""

IMPACT = "/Users/jperr/Documents/shorts/brand/fonts/Bangers-Regular.ttf"
COURIER = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"
FUTURA = "/System/Library/Fonts/Supplemental/Futura.ttc"
DIDOT = "/System/Library/Fonts/Supplemental/Didot.ttc"
ROUNDED = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"

WHITE = (245, 245, 240, 255)
PLAT = (232, 236, 241, 255)
ACCENT = (46, 107, 255, 255)  # Sapphire Glow #2E6BFF
STROKE = (0, 0, 0, 255)

STOPS = {"THE","A","AN","AND","OR","OF","TO","IN","ON","AT","FOR","FROM",
         "IS","ARE","WAS","WERE","BE","BEEN","BEING","HE","SHE","IT","THEY",
         "HIS","HER","THEIR","WHEN","WATCH","THIS","THAT","ALL","TIMES"}

words = title.split() or [" "]
# vertical anchor of the title block. production passes a top-banner fraction
# (the cold-open hook sits over live footage where the citation later lands);
# default 0.5 keeps the centered look for demos / standalone use.
CX, CY = W // 2, int(H * float(os.environ.get("TITLE_ANCHOR_FRAC", 0.5)))


def accent_index():
    best, best_len = -1, -1
    for i, w in enumerate(words):
        bare = "".join(ch for ch in w if ch.isalpha())
        if bare in STOPS:
            continue
        if len(bare) > best_len:
            best_len, best = len(bare), i
    return best if best >= 0 else len(words) - 1


acc = accent_index()


def ttc(path, want):
    for i in range(24):
        try:
            f = ImageFont.truetype(path, 40, index=i)
        except Exception:
            break
        if want.lower() in " ".join(f.getname()).lower():
            return i
    return 0


def wraplines(font, maxw):
    sp = font.getlength(" ")
    lines, cur, w = [], [], 0.0
    for i, word in enumerate(words):
        ww = font.getlength(word)
        t = ww if not cur else w + sp + ww
        if cur and t > maxw:
            lines.append(cur)
            cur, w = [(i, word)], ww
        else:
            cur.append((i, word))
            w = t
    if cur:
        lines.append(cur)
    return lines


def linew(line, font):
    sp = font.getlength(" ")
    return sum(font.getlength(w) for _, w in line) + sp * (len(line) - 1)


def fit(path, index=0, maxw=None, top=170):
    maxw = maxw or int(W * 0.88)
    for size in range(min(top, W // 6), 49, -2):
        f = ImageFont.truetype(path, size, index=index)
        ls = wraplines(f, maxw)
        if len(ls) <= 2 and max(linew(l, f) for l in ls) <= maxw:
            return size, ls
    f = ImageFont.truetype(path, 50, index=index)
    return 50, wraplines(f, maxw)


def render(lines, path, fs, scale, fill, accf, index=0, strokew=None, gapf=0.10):
    f = ImageFont.truetype(path, max(8, int(round(fs * scale))), index=index)
    sw = strokew if strokew is not None else max(4, int(fs * scale) // 10)
    asc, desc = f.getmetrics()
    lh, gap = asc + desc, int(fs * scale * gapf)
    sp = f.getlength(" ")

    def lw(line):
        return sum(f.getlength(w) for _, w in line) + sp * (len(line) - 1)

    tw = max(lw(l) for l in lines)
    th = lh * len(lines) + gap * (len(lines) - 1)
    pad = sw + 6
    img = Image.new("RGBA", (int(tw + 2 * pad), int(th + 2 * pad)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = pad
    for line in lines:
        x = (img.width - lw(line)) / 2
        for i, w in line:
            d.text((x, y), w, font=f, fill=accf if i == acc else fill,
                   stroke_width=sw, stroke_fill=STROKE)
            x += f.getlength(w) + sp
        y += lh + gap
    return img


def fade(img, a):
    if a >= 0.999:
        return img
    out = img.copy()
    out.putalpha(out.getchannel("A").point(lambda v: int(v * a)))
    return out


def tint(img, color):
    out = Image.new("RGBA", img.size, color)
    out.putalpha(img.getchannel("A"))
    return out


def put(canvas, img, cx, cy):
    canvas.alpha_composite(img, (int(cx - img.width / 2), int(cy - img.height / 2)))


def blank():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))


def ease_out(p):
    return 1 - (1 - p) ** 3


def elastic(p):
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return pow(2, -10 * p) * math.sin((p - 0.075) * (2 * math.pi) / 0.3) + 1


def clamp(v, a, b):
    return max(a, min(b, v))


# ---------- styles ----------

def glitch():
    fi = ttc(FUTURA, "condensed extrabold")
    fs, lines = fit(FUTURA, index=fi)
    core = render(lines, FUTURA, fs, 1.0, WHITE, ACCENT, index=fi)
    red = tint(core, (255, 40, 70, 200))
    cyn = tint(core, (0, 255, 240, 200))
    pad = 36
    intro, outt = 0.38, 0.28
    mid0, mid1 = 1.22, 1.36
    rng = random.Random(99)
    plan = {}
    for k in range(round(dur * fps) + 1):
        t = k / fps
        amt = 0.0
        show = True
        if t < intro:
            p = t / intro
            show = rng.random() < 0.30 + 0.70 * p
            amt = 1.0 - p
        if mid0 <= t < mid1:
            amt = 0.8
        if t >= dur - outt:
            p = (t - (dur - outt)) / outt
            show = rng.random() < 1.0 - p
            amt = p
        plan[k] = (show, amt,
                   rng.randint(-9, 9), rng.randint(-4, 4),
                   rng.randint(-9, 9), rng.randint(-4, 4),
                   rng.randrange(1 << 30))

    def banner(amt, dx1, dy1, dx2, dy2, seed):
        img = Image.new("RGBA", (core.width + 2 * pad, core.height + 2 * pad), (0, 0, 0, 0))
        img.alpha_composite(red, (pad + int(dx1 * amt), pad + int(dy1 * amt)))
        img.alpha_composite(cyn, (pad + int(dx2 * amt), pad + int(dy2 * amt)))
        img.alpha_composite(core, (pad, pad))
        if amt < 0.05:
            return img
        r = random.Random(seed)
        out = img.copy()
        for _ in range(r.randint(2, 4)):
            y0 = r.randrange(0, max(1, img.height - 14))
            hh = r.randrange(8, max(9, img.height // 5))
            dx = int(r.randrange(-30, 31) * amt)
            region = img.crop((0, y0, img.width, min(img.height, y0 + hh)))
            out.paste((0, 0, 0, 0), (0, y0, img.width, min(img.height, y0 + hh)))
            out.paste(region, (dx, y0), region)
        return out

    def fr(t):
        c = blank()
        show, amt, a, b, x, y, seed = plan[int(round(t * fps))]
        if not show:
            return c
        put(c, banner(amt, a, b, x, y, seed), CX, CY)
        return c

    ev = [{"t": 0.02, "kind": "zap"}, {"t": 0.13, "kind": "zap"},
          {"t": 0.25, "kind": "zap"}, {"t": 0.0, "kind": "crackle", "dur": intro},
          {"t": mid0, "kind": "zap"},
          {"t": dur - outt, "kind": "zap"},
          {"t": dur - outt, "kind": "crackle", "dur": outt}]
    return fr, ev


# only one title animation: glitch. it is the channel default for every short.
fr, events = glitch()
os.makedirs(outdir, exist_ok=True)
n = round(dur * fps)
for k in range(n):
    fr(k / fps).save(os.path.join(outdir, f"f_{k+1:04d}.png"))

if label:
    lf = ImageFont.truetype(IMPACT, 42)
    tw = lf.getlength(label)
    li = Image.new("RGBA", (int(tw + 48), 74), (0, 0, 0, 0))
    d = ImageDraw.Draw(li)
    d.rounded_rectangle((0, 0, li.width - 1, 73), radius=16, fill=(10, 12, 16, 200))
    d.text((24, 12), label, font=lf, fill=PLAT)
    li.save(os.path.join(outdir, "label.png"))

json.dump({"style": style, "dur": dur, "fps": fps, "events": events},
          open(os.path.join(outdir, "events.json"), "w"), indent=1)
print(f"styles: {style} {n} frames @{fps}fps dur={dur}s events={len(events)}", file=sys.stderr)
