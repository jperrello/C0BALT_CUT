#!/usr/bin/env python3
# Transparent PNG end-card: a closing CTA headline (+ channel handle) so a short
# lands on an intentional beat instead of a dangling word. Impact, Platinum
# headline + Sapphire handle, thick black stroke — matches the brand overlays.
import sys
from PIL import Image, ImageDraw, ImageFont

line1 = (sys.argv[1] if len(sys.argv) > 1 else "FOLLOW FOR MORE").strip() or "FOLLOW FOR MORE"
line2 = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
out = sys.argv[3]
W, H = int(sys.argv[4]), int(sys.argv[5])

FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"
WHITE = (232, 236, 241, 255)    # Platinum #E8ECF1
BLUE = (46, 107, 255, 255)      # Sapphire Glow #2E6BFF — matches captions + title accent
STROKE = (0, 0, 0, 255)
maxw = int(W * 0.92)


def fit(text, lo, hi):
    for s in range(hi, lo - 1, -2):
        f = ImageFont.truetype(FONT, s)
        if f.getlength(text) <= maxw:
            return f
    return ImageFont.truetype(FONT, lo)


f1 = fit(line1, 40, 96)
rows = [(line1, WHITE, f1)]
if line2:
    rows.append((line2, BLUE, fit(line2, 30, 60)))


def lineh(f):
    a, d = f.getmetrics()
    return a + d


stroke = max(4, f1.size // 12)
gap = int(f1.size * 0.12)
widths = [f.getlength(t) for t, _, f in rows]
textw = max(widths)
texth = sum(lineh(f) for _, _, f in rows) + gap * (len(rows) - 1)
padx, pady = stroke + 8, stroke + 6
bw, bh = int(textw + 2 * padx), int(texth + 2 * pady)

img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
y = pady
for (t, color, f), w in zip(rows, widths):
    d.text(((bw - w) / 2, y), t, font=f, fill=color, stroke_width=stroke, stroke_fill=STROKE)
    y += lineh(f) + gap
img.save(out)
print(f"end-card: banner {bw}x{bh} fs={f1.size}", file=sys.stderr)
