from PIL import Image, ImageDraw, ImageFont
import glob, os, math

src = os.path.dirname(os.path.abspath(__file__))
frames = sorted(glob.glob(f"{src}/*.png"))
import re
frames = [f for f in frames if not re.match(r"sprite\d*\.png$", os.path.basename(f))]

n = len(frames)
cols = 9
rows = math.ceil(n / cols)
thumb_w = 190
sample = Image.open(frames[0])
thumb_h = int(sample.height * thumb_w / sample.width)

sheet = Image.new("RGB", (cols * thumb_w, rows * thumb_h), (0, 0, 0))

for i, path in enumerate(frames):
    img = Image.open(path).convert("RGB")
    img = img.resize((thumb_w, thumb_h), Image.LANCZOS)
    x = (i % cols) * thumb_w
    y = (i // cols) * thumb_h
    sheet.paste(img, (x, y))

base = os.path.join(src, "sprite.png")
if not os.path.exists(base):
    out = base
else:
    n = 1
    while os.path.exists(os.path.join(src, f"sprite{n}.png")):
        n += 1
    out = os.path.join(src, f"sprite{n}.png")
sheet.save(out, "PNG", optimize=True)
print(f"Saved {out}  ({cols}×{rows} grid, {n} frames, {sheet.width}×{sheet.height}px)")
