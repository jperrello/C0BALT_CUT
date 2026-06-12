#!/usr/bin/env python3
# render a title-transition style as a full-frame RGBA PNG sequence + events.json
# (SFX cue list) + label.png (style tag for the demo). one style per invocation.
# usage: styles.py <style> <title> <outdir> <W> <H> <dur> <fps> [label]
import json, math, os, random, sys
from PIL import Image, ImageDraw, ImageFont

style = sys.argv[1]
title = sys.argv[2].strip().upper()
outdir = sys.argv[3]
W, H = int(sys.argv[4]), int(sys.argv[5])
dur, fps = float(sys.argv[6]), int(sys.argv[7])
label = sys.argv[8] if len(sys.argv) > 8 else style.upper()

IMPACT = "/System/Library/Fonts/Supplemental/Impact.ttf"
COURIER = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"
FUTURA = "/System/Library/Fonts/Supplemental/Futura.ttc"
DIDOT = "/System/Library/Fonts/Supplemental/Didot.ttc"
ROUNDED = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"

WHITE = (245, 245, 240, 255)
PLAT = (232, 236, 241, 255)
ACCENT = (46, 107, 255, 255)  # Sapphire Glow #2E6BFF
STROKE = (0, 0, 0, 255)
CARBON = (16, 20, 24, 235)

STOPS = {"THE","A","AN","AND","OR","OF","TO","IN","ON","AT","FOR","FROM",
         "IS","ARE","WAS","WERE","BE","BEEN","BEING","HE","SHE","IT","THEY",
         "HIS","HER","THEIR","WHEN","WATCH","THIS","THAT","ALL","TIMES"}

words = title.split() or [" "]
CX, CY = W // 2, H // 2


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


def ease_in(p):
    return p ** 3


def elastic(p):
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return pow(2, -10 * p) * math.sin((p - 0.075) * (2 * math.pi) / 0.3) + 1


def clamp(v, a, b):
    return max(a, min(b, v))


# ---------- styles ----------

def slam():
    fs, lines = fit(IMPACT)
    master = render(lines, IMPACT, fs, 3.4, WHITE, ACCENT)
    full = render(lines, IMPACT, fs, 1.0, WHITE, ACCENT)
    land, settle, outt = 0.26, 0.14, 0.30

    def fr(t):
        c = blank()
        if t < land:
            p = t / land
            s = 3.4 - 2.4 * p * p
            img = master.resize((max(2, int(master.width * s / 3.4)),
                                 max(2, int(master.height * s / 3.4))), Image.LANCZOS)
            put(c, fade(img, 0.45 + 0.55 * p), CX, CY)
            return c
        if t < land + settle:
            p = (t - land) / settle
            s = 1 - 0.05 * math.sin(math.pi * p)
            img = full.resize((max(2, int(full.width * s)), max(2, int(full.height * s))), Image.LANCZOS)
            put(c, img, CX, CY)
            return c
        if t < dur - outt:
            put(c, full, CX, CY)
            return c
        p = clamp((t - (dur - outt)) / outt, 0, 1)
        s = (1 - p) ** 1.6
        if s < 0.02:
            return c
        img = full.resize((max(2, int(full.width * s)), max(2, int(full.height * s))), Image.LANCZOS)
        put(c, img, CX, CY)
        return c

    return fr, [{"t": 0.0, "kind": "riser", "dur": land},
                {"t": land, "kind": "boom"}]


def typewriter():
    fs, lines = fit(COURIER, maxw=int(W * 0.86), top=120)
    f = ImageFont.truetype(COURIER, fs)
    asc, desc = f.getmetrics()
    lh, gap = asc + desc, int(fs * 0.18)
    sw = max(3, fs // 12)
    th = lh * len(lines) + gap * (len(lines) - 1)
    y0 = CY - th // 2
    chars = []
    for li, line in enumerate(lines):
        x = CX - linew(line, f) / 2
        y = y0 + li * (lh + gap)
        for i, w in line:
            for ch in w:
                chars.append((x, y, ch, ACCENT if i == acc else WHITE))
                x += f.getlength(ch)
            chars.append((x, y, " ", WHITE))
            x += f.getlength(" ")
    while chars and chars[-1][2] == " ":
        chars.pop()
    t0 = 0.14
    ttime = min(1.5, dur * 0.50)
    step = ttime / max(1, len(chars))
    type_end = t0 + step * len(chars)
    cw = f.getlength("M") * 0.58

    def fr(t):
        c = blank()
        k = clamp(int((t - t0) / step) + (1 if t >= t0 else 0), 0, len(chars))
        d = ImageDraw.Draw(c)
        for x, y, ch, col in chars[:k]:
            if ch == " ":
                continue
            d.text((x, y), ch, font=f, fill=col, stroke_width=sw, stroke_fill=STROKE)
        typing = t0 <= t < type_end
        blink = int(t * 2.6) % 2 == 0
        if k < len(chars) or typing or blink:
            if t >= t0 and t < dur - 0.30:
                nx = chars[k][0] if k < len(chars) else chars[-1][0] + f.getlength(chars[-1][2])
                ny = chars[k][1] if k < len(chars) else chars[-1][1]
                d.rectangle((nx + 2, ny + int(asc * 0.16), nx + 2 + cw, ny + asc), fill=PLAT)
        if t > dur - 0.25:
            return fade(c, clamp((dur - t) / 0.25, 0, 1))
        return c

    ev = [{"t": round(t0 + i * step, 4), "kind": "key"}
          for i, (_, _, ch, _) in enumerate(chars) if ch != " "]
    ev.append({"t": round(type_end + 0.05, 4), "kind": "ding"})
    return fr, ev


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


def bounce():
    path = ROUNDED if os.path.exists(ROUNDED) else IMPACT
    fs, lines = fit(path, top=150)
    f = ImageFont.truetype(path, fs)
    asc, desc = f.getmetrics()
    lh, gap = asc + desc, int(fs * 0.12)
    th = lh * len(lines) + gap * (len(lines) - 1)
    y0 = CY - th // 2
    cards, centers = [], []
    for li, line in enumerate(lines):
        x = CX - linew(line, f) / 2
        y = y0 + li * (lh + gap)
        for i, w in line:
            ww = f.getlength(w)
            cards.append(render([[(i, w)]], path, fs, 1.5, WHITE, ACCENT))
            centers.append((x + ww / 2, y + lh / 2))
            x += ww + f.getlength(" ")
    full = blank()
    for img, (cx, cy) in zip(cards, centers):
        small = img.resize((max(2, int(img.width / 1.5)), max(2, int(img.height / 1.5))), Image.LANCZOS)
        put(full, small, cx, cy)
    full = full.crop((0, 0, W, H))
    nw = len(cards)
    step = min(0.17, max(0.06, (dur - 1.0 - 0.08) / max(1, nw - 1)))
    starts = [0.08 + step * i for i in range(nw)]
    bdur, outt = 0.32, 0.28

    def fr(t):
        c = blank()
        if t >= dur - outt:
            p = clamp((t - (dur - outt)) / outt, 0, 1)
            s = (1 - p) ** 1.5
            if s < 0.02:
                return c
            img = full.resize((max(2, int(W * s)), max(2, int(H * s))), Image.LANCZOS)
            put(c, img, CX, CY)
            return c
        for img, (cx, cy), st, i in zip(cards, centers, starts, range(nw)):
            p = (t - st) / bdur
            if p <= 0:
                continue
            s = max(0.0, elastic(clamp(p, 0, 1)))
            if s < 0.02:
                continue
            w2 = max(2, int(img.width * s / 1.5))
            h2 = max(2, int(img.height * s / 1.5))
            sc = img.resize((w2, h2), Image.LANCZOS)
            rot = (1 - clamp(p, 0, 1)) * 10 * (1 if i % 2 else -1)
            if abs(rot) > 0.5:
                sc = sc.rotate(rot, expand=True, resample=Image.BICUBIC)
            put(c, sc, cx, cy)
        return c

    ev = [{"t": round(st + 0.05, 4), "kind": "pop", "pitch": round(420 * (1.13 ** i), 1)}
          for i, st in enumerate(starts)]
    ev.append({"t": round(starts[-1] + 0.22, 4), "kind": "boing"})
    return fr, ev


def news():
    fi = ttc(FUTURA, "condensed extrabold")
    fs, lines = fit(FUTURA, index=fi, maxw=int(W * 0.78), top=120)
    text = render(lines, FUTURA, fs, 1.0, WHITE, ACCENT, index=fi, strokew=max(2, fs // 30))
    bh = text.height + int(fs * 0.55)
    bar = Image.new("RGBA", (W, bh), CARBON)
    d = ImageDraw.Draw(bar)
    d.rectangle((0, 0, 18, bh), fill=ACCENT)
    d.rectangle((0, bh - 7, W, bh), fill=ACCENT)
    by = CY - bh // 2
    tx, ty = (W - text.width) // 2, by + (bh - text.height) // 2
    slide, wend, outt = 0.22, 0.55, 0.28

    def fr(t):
        c = blank()
        x = 0.0
        wipe = 1.0
        if t < slide:
            x = -W * (1 - ease_out(t / slide))
            wipe = 0.0
        elif t < wend:
            wipe = ease_out((t - slide) / (wend - slide))
        elif t >= dur - outt:
            x = W * ease_in(clamp((t - (dur - outt)) / outt, 0, 1))
        c.alpha_composite(bar, (int(x), by))
        tw = int(text.width * wipe)
        if tw > 2:
            c.alpha_composite(text.crop((0, 0, tw, text.height)), (int(tx + x), ty))
        return c

    return fr, [{"t": 0.0, "kind": "whoosh", "dur": slide + 0.06, "up": 1},
                {"t": 0.24, "kind": "ident"},
                {"t": dur - outt, "kind": "whoosh", "dur": outt, "up": 0}]


def cinematic():
    di = ttc(DIDOT, "bold")
    tr0, tr1 = 0.42, 0.05
    maxw = int(W * 0.92)

    def measure(f, fs, trpx):
        sp = f.getlength(" ") + trpx
        lines, cur, w = [], [], 0.0
        for i, word in enumerate(words):
            ww = sum(f.getlength(ch) for ch in word) + trpx * (len(word) - 1)
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

    fs, f, lines = None, None, None
    for size in range(130, 39, -2):
        g = ImageFont.truetype(DIDOT, size, index=di)
        ls = measure(g, size, tr0 * size)
        sp = g.getlength(" ") + tr0 * size
        wide = max(sum(g.getlength(c) for _, w in l for c in w)
                   + tr0 * size * sum(len(w) - 1 for _, w in l)
                   + sp * (len(l) - 1) for l in ls)
        if len(ls) <= 2 and wide <= maxw:
            fs, f, lines = size, g, ls
            break
    if fs is None:
        fs = 40
        f = ImageFont.truetype(DIDOT, fs, index=di)
        lines = measure(f, fs, tr0 * fs)
    asc, desc = f.getmetrics()
    lh, gap = asc + desc, int(fs * 0.22)
    th = lh * len(lines) + gap * (len(lines) - 1)
    y0 = CY - th // 2
    form, outt = 1.15, 0.50

    def draw(trpx, a, linep):
        c = blank()
        d = ImageDraw.Draw(c)
        sp = f.getlength(" ") + trpx
        widest = 0.0
        for li, line in enumerate(lines):
            lw = (sum(f.getlength(ch) for _, w in line for ch in w)
                  + trpx * sum(len(w) - 1 for _, w in line) + sp * (len(line) - 1))
            widest = max(widest, lw)
            x = CX - lw / 2
            y = y0 + li * (lh + gap)
            for _, w in line:
                for ch in w:
                    d.text((x, y), ch, font=f, fill=PLAT, stroke_width=2, stroke_fill=(0, 0, 0, 200))
                    x += f.getlength(ch) + trpx
                x += sp - trpx
        if linep > 0.01:
            half = widest * 0.31 * linep
            ly = y0 + th + int(fs * 0.35)
            d.rectangle((CX - half, ly, CX + half, ly + max(3, fs // 16)), fill=ACCENT)
        return fade(c, a)

    def fr(t):
        if t >= dur - outt:
            p = clamp((t - (dur - outt)) / outt, 0, 1)
            return draw((tr1 + 0.06 * p) * fs, 1 - p, 1 - p)
        p = ease_out(clamp(t / form, 0, 1))
        a = ease_out(clamp(t / 0.9, 0, 1))
        lp = ease_out(clamp((t - 0.45) / (form - 0.45), 0, 1))
        return draw((tr0 + (tr1 - tr0) * p) * fs, a, lp)

    return fr, [{"t": 0.0, "kind": "swell", "dur": form},
                {"t": form, "kind": "thump"}]


BUILDERS = {"slam": slam, "typewriter": typewriter, "glitch": glitch,
            "bounce": bounce, "news": news, "cinematic": cinematic}

fr, events = BUILDERS[style]()
os.makedirs(outdir, exist_ok=True)
n = round(dur * fps)
for k in range(n):
    fr(k / fps).save(os.path.join(outdir, f"f_{k+1:04d}.png"))

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
