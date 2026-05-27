#!/usr/bin/env python3
# Render a transparent PNG banner: "Original video:" in blue + title in white.
# Wraps long titles to a 2nd line. Auto-fits font size to a target width.
import sys
from PIL import Image, ImageDraw, ImageFont

title = sys.argv[1].strip()
out = sys.argv[2]
W = int(sys.argv[3])
H = int(sys.argv[4])

FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"
LABEL = "Original video:"
BLUE = (0, 229, 255, 255)       # electric cyan #00E5FF — matches burn-subtitles + title accent
WHITE = (245, 245, 240, 255)
STROKE = (0, 0, 0, 255)

maxw = int(W * 0.88)


def measure(font, text):
    return font.getlength(text)


def wrap_title(font, text):
    words = text.split() or [" "]
    space = font.getlength(" ")
    lines, cur, curw = [], [], 0.0
    for w in words:
        ww = font.getlength(w)
        add = ww if not cur else curw + space + ww
        if cur and add > maxw:
            lines.append(" ".join(cur))
            cur, curw = [w], ww
        else:
            cur.append(w)
            curw = add
    if cur:
        lines.append(" ".join(cur))
    return lines[:2]  # cap at 2 lines; truncate rest


def fits(font):
    label_w = font.getlength(LABEL + " ")
    title_lines = wrap_title(font, title)
    first_line_total = label_w + font.getlength(title_lines[0])
    widest = max(first_line_total, *(font.getlength(l) for l in title_lines[1:]) if len(title_lines) > 1 else [0])
    return widest <= maxw, title_lines


fs, font, lines = None, None, None
for size in range(72, 31, -2):
    f = ImageFont.truetype(FONT, size)
    ok, ls = fits(f)
    if ok:
        fs, font, lines = size, f, ls
        break
if fs is None:
    fs = 32
    font = ImageFont.truetype(FONT, fs)
    _, lines = fits(font)

stroke = max(3, fs // 12)
asc, desc = font.getmetrics()
lineh = asc + desc
gap = int(fs * 0.10)
space = font.getlength(" ")

label_w = font.getlength(LABEL)
first_title_w = font.getlength(lines[0])
first_row_w = label_w + space + first_title_w
rest_w = max((font.getlength(l) for l in lines[1:]), default=0)
textw = max(first_row_w, rest_w)
texth = lineh * len(lines) + gap * (len(lines) - 1)

padx = stroke + 6
pady = stroke + 4
bw = int(textw + 2 * padx)
bh = int(texth + 2 * pady)

img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

y = pady
# Row 1: label (blue) + first title line (white)
x = padx
d.text((x, y), LABEL, font=font, fill=BLUE,
       stroke_width=stroke, stroke_fill=STROKE)
x += label_w + space
d.text((x, y), lines[0], font=font, fill=WHITE,
       stroke_width=stroke, stroke_fill=STROKE)
y += lineh + gap

# Row 2+: continuation lines of title (white)
for l in lines[1:]:
    x = padx
    d.text((x, y), l, font=font, fill=WHITE,
           stroke_width=stroke, stroke_fill=STROKE)
    y += lineh + gap

img.save(out)
print(f"source-credit: banner {bw}x{bh} fs={fs} lines={len(lines)}", file=sys.stderr)
