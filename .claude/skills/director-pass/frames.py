import sys, os, json, math, subprocess, argparse


def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def probe(path):
    p = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", path])
    try:
        return float((p.stdout or "0").strip())
    except Exception:
        return 0.0


def grab(clip, t, dst, tw):
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.3f" % max(0.0, t),
         "-i", clip, "-frames:v", "1", "-vf", "scale=%d:-2" % tw, dst])
    return os.path.isfile(dst)


# Build a labelled contact sheet (row-major grid) so one Claude vision call can
# WATCH the whole short. Each cell shows the frame at its timestamp; the burned
# captions/b-roll/framing are all visible, so the reviewer judges what it sees.
def sheet(clip, outdir, n, tw):
    from PIL import Image, ImageDraw, ImageFont
    dur = probe(clip)
    if dur <= 0:
        return None
    n = max(4, min(20, n))
    # evenly spaced across [0, dur], inclusive of the open and (near) the close
    ts = [round(i / (n - 1) * max(0.0, dur - 0.12), 3) for i in range(n)]

    font = None
    for fp in ("/System/Library/Fonts/Supplemental/Impact.ttf",
               "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if os.path.isfile(fp):
            try:
                font = ImageFont.truetype(fp, 20)
                break
            except Exception:
                font = None
    if font is None:
        font = ImageFont.load_default()

    thumbs = []
    for i, t in enumerate(ts):
        fp = os.path.join(outdir, "f%02d.png" % i)
        if grab(clip, t, fp, tw):
            try:
                thumbs.append((i, t, Image.open(fp).convert("RGB")))
            except Exception:
                pass
    if not thumbs:
        return None

    th = max(im.height for _, _, im in thumbs)
    label_h = 26
    pad = 6
    cols = 4
    rows = math.ceil(len(thumbs) / cols)
    cell_w = tw + pad
    cell_h = th + label_h + pad
    W = cols * cell_w + pad
    H = rows * cell_h + pad
    canvas = Image.new("RGB", (W, H), (16, 20, 24))
    draw = ImageDraw.Draw(canvas)

    for k, (i, t, im) in enumerate(thumbs):
        r, c = divmod(k, cols)
        x = pad + c * cell_w
        y = pad + r * cell_h
        canvas.paste(im, (x, y))
        draw.text((x + 4, y + th + 3), "t=%.1fs  (#%d)" % (t, k),
                  fill=(232, 236, 241), font=font)

    out = os.path.join(outdir, "sheet.png")
    canvas.save(out)
    return {
        "sheet": out,
        "cols": cols,
        "rows": rows,
        "duration": round(dur, 3),
        "frames": [{"k": k, "t": t} for k, (i, t, _im) in enumerate(thumbs)],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("outdir")
    ap.add_argument("--n", type=int, default=int(os.environ.get("DIRECTOR_FRAMES", "12")))
    ap.add_argument("--tw", type=int, default=200)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    info = sheet(a.clip, a.outdir, a.n, a.tw)
    if not info:
        print("{}")
        sys.exit(1)
    print(json.dumps(info))


if __name__ == "__main__":
    main()
