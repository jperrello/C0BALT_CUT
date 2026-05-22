#!/usr/bin/env python3
# render a tight title-card banner PNG (transparent) for the title-transition skill.
# the local ffmpeg build has no drawtext, so the card is a PIL-rendered PNG that
# ffmpeg slides across the frame with an overlay x-expression.
import sys
from PIL import Image, ImageDraw, ImageFont

title = sys.argv[1].strip().upper()
out = sys.argv[2]
W = int(sys.argv[3])
H = int(sys.argv[4])
spec = sys.argv[5] if len(sys.argv) > 5 else "auto"

FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
WHITE = (255, 255, 255, 255)
ACCENT = (255, 214, 51, 255)
PANEL = (15, 15, 18, 212)
STROKE = (0, 0, 0, 255)

maxw = int(W * 0.84)
words = title.split() or [" "]


def wrap(font):
    space = font.getlength(" ")
    lines, cur, curw = [], [], 0.0
    for word in words:
        ww = font.getlength(word)
        add = ww if not cur else curw + space + ww
        if cur and add > maxw:
            lines.append(cur)
            cur, curw = [word], ww
        else:
            cur.append(word)
            curw = add
    if cur:
        lines.append(cur)
    return lines


def linewidth(line, font):
    space = font.getlength(" ")
    return sum(font.getlength(w) for w in line) + space * (len(line) - 1)


if spec == "auto":
    fs, font, lines = None, None, None
    for size in range(min(140, W // 8), 41, -2):
        f = ImageFont.truetype(FONT, size)
        ls = wrap(f)
        if len(ls) <= 2 and max(linewidth(l, f) for l in ls) <= maxw:
            fs, font, lines = size, f, ls
            break
    if fs is None:
        fs = 44
        font = ImageFont.truetype(FONT, fs)
        lines = wrap(font)
else:
    fs = int(spec)
    font = ImageFont.truetype(FONT, fs)
    lines = wrap(font)

stroke = max(3, fs // 14)
asc, desc = font.getmetrics()
lineh = asc + desc
gap = int(fs * 0.12)
padx = int(fs * 0.55)
pady = int(fs * 0.40)

textw = max(linewidth(l, font) for l in lines)
texth = lineh * len(lines) + gap * (len(lines) - 1)
bw = int(textw + 2 * padx + 2 * stroke)
bh = int(texth + 2 * pady + 2 * stroke)

img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=int(fs * 0.32),
                    fill=PANEL, outline=ACCENT, width=max(3, fs // 24))

space = font.getlength(" ")
y = pady + stroke
for line in lines:
    x = (bw - linewidth(line, font)) / 2
    for word in line:
        d.text((x, y), word, font=font, fill=WHITE,
               stroke_width=stroke, stroke_fill=STROKE)
        x += font.getlength(word) + space
    y += lineh + gap

img.save(out)
print(f"title-transition: banner {bw}x{bh} fs={fs} lines={len(lines)}", file=sys.stderr)
