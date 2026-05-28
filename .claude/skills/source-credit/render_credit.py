#!/usr/bin/env python3
# Render a transparent PNG banner: "Original video:" in blue + title in white.
# Wraps long titles across up to 3 lines, auto-fits the font, centers every line.
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

maxw = int(W * 0.90)
maxlines = 3


# Wrap the title across lines. Line 1 shares its budget with the label that
# sits in front of it; later lines get the full width.
def wrap_title(font):
    words = title.split() or [" "]
    space = font.getlength(" ")
    budget = maxw - font.getlength(LABEL + " ")
    lines, cur, curw = [], [], 0.0
    for w in words:
        ww = font.getlength(w)
        add = ww if not cur else curw + space + ww
        if cur and add > budget:
            lines.append(" ".join(cur))
            cur, curw = [w], ww
            budget = maxw
        else:
            cur.append(w)
            curw = add
    if cur:
        lines.append(" ".join(cur))
    return lines[:maxlines]


def fits(font):
    lines = wrap_title(font)
    row1 = font.getlength(LABEL + " ") + font.getlength(lines[0])
    widest = max([row1] + [font.getlength(l) for l in lines[1:]])
    return widest <= maxw, lines


fs, font, lines = None, None, None
for size in range(60, 39, -2):
    f = ImageFont.truetype(FONT, size)
    ok, ls = fits(f)
    if ok:
        fs, font, lines = size, f, ls
        break
if fs is None:
    fs = 40
    font = ImageFont.truetype(FONT, fs)
    _, lines = fits(font)

stroke = max(3, fs // 12)
asc, desc = font.getmetrics()
lineh = asc + desc
gap = int(fs * 0.10)
space = font.getlength(" ")

label_w = font.getlength(LABEL)
row_widths = [label_w + space + font.getlength(lines[0])]
row_widths += [font.getlength(l) for l in lines[1:]]
textw = max(row_widths)
texth = lineh * len(lines) + gap * (len(lines) - 1)

padx = stroke + 6
pady = stroke + 4
bw = int(textw + 2 * padx)
bh = int(texth + 2 * pady)

img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

y = pady
# Row 1: label (blue) + first title line (white), centered as one unit.
x = (bw - row_widths[0]) / 2
d.text((x, y), LABEL, font=font, fill=BLUE,
       stroke_width=stroke, stroke_fill=STROKE)
x += label_w + space
d.text((x, y), lines[0], font=font, fill=WHITE,
       stroke_width=stroke, stroke_fill=STROKE)
y += lineh + gap

# Row 2+: continuation lines of title (white), each centered.
for i, l in enumerate(lines[1:], 1):
    x = (bw - row_widths[i]) / 2
    d.text((x, y), l, font=font, fill=WHITE,
           stroke_width=stroke, stroke_fill=STROKE)
    y += lineh + gap

img.save(out)
print(f"source-credit: banner {bw}x{bh} fs={fs} lines={len(lines)}", file=sys.stderr)
