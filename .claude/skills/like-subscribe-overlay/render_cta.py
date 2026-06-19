#!/usr/bin/env python3
# render a "LIKE & SUBSCRIBE" CTA banner PNG (transparent) for the
# like-subscribe-overlay skill. brand-matched to title-transition /
# burn-subtitles: Impact text, white with a cyan accent, thick black stroke.
# includes a synthesized thumbs-up icon (left) and bell icon (right).
import sys
from PIL import Image, ImageDraw, ImageFont

out = sys.argv[1]
W = int(sys.argv[2])
H = int(sys.argv[3])

FONT = "/Users/jperr/Documents/shorts/brand/fonts/Bangers-Regular.ttf"
WHITE = (245, 245, 240, 255)
ACCENT = (46, 107, 255, 255)
STROKE = (0, 0, 0, 255)

text_top = "LIKE & SUBSCRIBE"
text_bot = "FOR MORE"

# target text height: ~7% of frame height (readable on phone, doesn't dominate)
fs_top = max(48, int(H * 0.055))
fs_bot = max(36, int(H * 0.035))
font_top = ImageFont.truetype(FONT, fs_top)
font_bot = ImageFont.truetype(FONT, fs_bot)

# accent the second word ("SUBSCRIBE") and the icon glow
def linew(font, s):
    return font.getlength(s)

words_top = text_top.split()
space_t = linew(font_top, " ")
top_w = sum(linew(font_top, w) for w in words_top) + space_t * (len(words_top) - 1)
bot_w = linew(font_bot, text_bot)

# icon size scales with fs_top
icon = int(fs_top * 1.15)
gap_icon = int(fs_top * 0.4)

# layout: [thumb] LIKE & SUBSCRIBE [bell]   /  FOR MORE
row_w = int(icon + gap_icon + top_w + gap_icon + icon)
stroke = max(4, fs_top // 10)
pad = stroke + 8

bw = int(max(row_w, bot_w) + 2 * pad)
bh = int(icon + int(fs_bot * 1.3) + int(fs_top * 0.25) + 2 * pad)

img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
d = ImageDraw.Draw(img)


def stroked_text(xy, s, font, fill):
    d.text(xy, s, font=font, fill=fill, stroke_width=stroke, stroke_fill=STROKE)


def thumb_up(cx, cy, sz):
    # stylized thumbs-up: rounded thumb + square palm, white fill, black stroke
    # bounding box approx sz x sz, centered on (cx, cy)
    s = sz
    x0, y0 = cx - s // 2, cy - s // 2
    # palm/fingers block (lower 2/3)
    palm = [(x0 + int(s * 0.20), y0 + int(s * 0.42)),
            (x0 + int(s * 0.92), y0 + int(s * 0.95))]
    # thumb (upper portion, sticking up-left)
    thumb_poly = [
        (x0 + int(s * 0.20), y0 + int(s * 0.55)),
        (x0 + int(s * 0.35), y0 + int(s * 0.05)),
        (x0 + int(s * 0.55), y0 + int(s * 0.05)),
        (x0 + int(s * 0.60), y0 + int(s * 0.42)),
        (x0 + int(s * 0.92), y0 + int(s * 0.42)),
        (x0 + int(s * 0.92), y0 + int(s * 0.95)),
        (x0 + int(s * 0.20), y0 + int(s * 0.95)),
    ]
    d.polygon(thumb_poly, fill=WHITE, outline=STROKE)
    # thicken outline
    for w in range(1, max(3, stroke // 2)):
        d.line(thumb_poly + [thumb_poly[0]], fill=STROKE, width=stroke)
    # cuff
    d.line([(x0 + int(s * 0.20), y0 + int(s * 0.55)),
            (x0 + int(s * 0.20), y0 + int(s * 0.95))], fill=STROKE, width=stroke)


def bell(cx, cy, sz):
    # stylized bell: dome + flare + clapper
    s = sz
    x0, y0 = cx - s // 2, cy - s // 2
    body = [
        (x0 + int(s * 0.50), y0 + int(s * 0.05)),
        (x0 + int(s * 0.20), y0 + int(s * 0.45)),
        (x0 + int(s * 0.15), y0 + int(s * 0.75)),
        (x0 + int(s * 0.85), y0 + int(s * 0.75)),
        (x0 + int(s * 0.80), y0 + int(s * 0.45)),
    ]
    d.polygon(body, fill=WHITE, outline=STROKE)
    d.line(body + [body[0]], fill=STROKE, width=stroke)
    # flare
    d.rectangle([(x0 + int(s * 0.10), y0 + int(s * 0.72)),
                 (x0 + int(s * 0.90), y0 + int(s * 0.82))],
                fill=WHITE, outline=STROKE, width=stroke)
    # clapper
    d.ellipse([(x0 + int(s * 0.42), y0 + int(s * 0.82)),
               (x0 + int(s * 0.58), y0 + int(s * 0.98))],
              fill=WHITE, outline=STROKE, width=stroke)
    # accent dot on top
    d.ellipse([(x0 + int(s * 0.44), y0 + int(s * 0.00)),
               (x0 + int(s * 0.56), y0 + int(s * 0.12))],
              fill=ACCENT, outline=STROKE, width=max(2, stroke // 2))


# row position
row_y = pad
row_x = (bw - row_w) // 2

thumb_up(row_x + icon // 2, row_y + icon // 2, icon)

x = row_x + icon + gap_icon
text_y = row_y + (icon - fs_top) // 2 - int(fs_top * 0.1)
for i, w in enumerate(words_top):
    color = ACCENT if w == "SUBSCRIBE" else WHITE
    stroked_text((x, text_y), w, font_top, color)
    x += linew(font_top, w) + space_t

bell_cx = row_x + icon + gap_icon + int(top_w) + gap_icon + icon // 2
bell(bell_cx, row_y + icon // 2, icon)

# bottom row
bot_y = row_y + icon + int(fs_top * 0.15)
bot_x = (bw - bot_w) // 2
stroked_text((bot_x, bot_y), text_bot, font_bot, WHITE)

img.save(out)
print(f"like-subscribe-overlay: banner {bw}x{bh} fs={fs_top}/{fs_bot}", file=sys.stderr)
