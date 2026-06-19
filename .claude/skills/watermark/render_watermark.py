# Render the @C0BALT_CUT channel watermark as a transparent PNG.
# Platinum type with the slashed-zero in Sapphire Glow, semi-transparent
# so it brands without shouting. Palette: brand/BRAND.md.
import sys
from PIL import Image, ImageDraw, ImageFont

out = sys.argv[1]
W = int(sys.argv[2])
H = int(sys.argv[3])

FONT = "/Users/jperr/Documents/shorts/brand/fonts/Bangers-Regular.ttf"
PLATINUM = (232, 236, 241, 200)
SAPPHIRE = (46, 107, 255, 230)
STROKE = (0, 0, 0, 200)

parts = [("@C", PLATINUM), ("0", SAPPHIRE), ("BALT_CUT", PLATINUM)]

fs = max(26, int(H * 0.021))
font = ImageFont.truetype(FONT, fs)
stroke = max(2, fs // 14)

asc, desc = font.getmetrics()
textw = sum(font.getlength(t) for t, _ in parts)
pad = stroke + 4
img = Image.new("RGBA", (int(textw) + 2 * pad, asc + desc + 2 * pad), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

x = pad
for t, fill in parts:
    d.text((x, pad), t, font=font, fill=fill, stroke_width=stroke, stroke_fill=STROKE)
    x += font.getlength(t)

img.save(out)
print(f"watermark: {img.width}x{img.height} fs={fs}", file=sys.stderr)
