#!/usr/bin/env python3
# render a tight title-card banner PNG (transparent) for the title-transition skill.
# Brand-matched to burn-subtitles: Impact, white with a cyan accent on every other
# word, thick black stroke, NO dark panel. Same visual language as the captions.
import sys
from PIL import Image, ImageDraw, ImageFont

title = sys.argv[1].strip().upper()
out = sys.argv[2]
W = int(sys.argv[3])
H = int(sys.argv[4])
spec = sys.argv[5] if len(sys.argv) > 5 else "auto"

FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"
WHITE = (245, 245, 240, 255)
ACCENT = (46, 107, 255, 255)  # Sapphire Glow #2E6BFF — matches burn-subtitles active-word
STROKE = (0, 0, 0, 255)

# Pick the accented word: the longest content word that isn't a stop word.
# Falls back to the last word so the title still has a visible accent.
STOPS = {"THE","A","AN","AND","OR","OF","TO","IN","ON","AT","FOR","FROM",
         "IS","ARE","WAS","WERE","BE","BEEN","BEING","HE","SHE","IT","THEY",
         "HIS","HER","THEIR","WHEN","WATCH","THE","THIS","THAT","ALL","TIMES"}
def accent_index(words):
    best = -1
    best_len = -1
    for i, w in enumerate(words):
        bare = "".join(ch for ch in w if ch.isalpha())
        if bare in STOPS:
            continue
        if len(bare) > best_len:
            best_len, best = len(bare), i
    return best if best >= 0 else len(words) - 1

maxw = int(W * 0.88)
words = title.split() or [" "]
acc_i = accent_index(words)


def wrap(font):
    space = font.getlength(" ")
    lines, cur, curw = [], [], 0.0
    for i, word in enumerate(words):
        ww = font.getlength(word)
        add = ww if not cur else curw + space + ww
        if cur and add > maxw:
            lines.append(cur)
            cur, curw = [(i, word)], ww
        else:
            cur.append((i, word))
            curw = add
    if cur:
        lines.append(cur)
    return lines


def linewidth(line, font):
    space = font.getlength(" ")
    return sum(font.getlength(w) for _, w in line) + space * (len(line) - 1)


if spec == "auto":
    fs, font, lines = None, None, None
    for size in range(min(180, W // 6), 51, -2):
        f = ImageFont.truetype(FONT, size)
        ls = wrap(f)
        if len(ls) <= 2 and max(linewidth(l, f) for l in ls) <= maxw:
            fs, font, lines = size, f, ls
            break
    if fs is None:
        fs = 52
        font = ImageFont.truetype(FONT, fs)
        lines = wrap(font)
else:
    fs = int(spec)
    font = ImageFont.truetype(FONT, fs)
    lines = wrap(font)

stroke = max(4, fs // 10)
asc, desc = font.getmetrics()
lineh = asc + desc
gap = int(fs * 0.10)

textw = max(linewidth(l, font) for l in lines)
texth = lineh * len(lines) + gap * (len(lines) - 1)
# small padding only for the stroke to breathe; NO panel.
padx = stroke + 4
pady = stroke + 4
bw = int(textw + 2 * padx)
bh = int(texth + 2 * pady)

img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

space = font.getlength(" ")
y = pady
for line in lines:
    x = (bw - linewidth(line, font)) / 2
    for idx, word in line:
        color = ACCENT if idx == acc_i else WHITE
        d.text((x, y), word, font=font, fill=color,
               stroke_width=stroke, stroke_fill=STROKE)
        x += font.getlength(word) + space
    y += lineh + gap

img.save(out)
print(f"title-transition: banner {bw}x{bh} fs={fs} lines={len(lines)} accent_word={acc_i}", file=sys.stderr)
