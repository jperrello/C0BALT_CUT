#!/usr/bin/env python3
# reframe-vertical: crop a horizontal video to 9:16, tracking the speaker.
# Builds a smoothed crop-x (and crop-y) path and drives ffmpeg's crop filter
# via a sendcmd file.
import json, subprocess, sys, argparse, os


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True,
    ).stdout
    d = json.loads(out)
    st = d["streams"][0]
    num, _, den = st["r_frame_rate"].partition("/")
    fps = float(num) / float(den) if float(den or 0) else 30.0
    return int(st["width"]), int(st["height"]), fps, float(d["format"]["duration"])


def even(n):
    n = int(round(n))
    return n - (n % 2)


def smooth(vals, alpha):
    out = []
    s = vals[0]
    for v in vals:
        s = alpha * v + (1 - alpha) * s
        out.append(s)
    # reverse pass to remove lag
    s = out[-1]
    for i in range(len(out) - 1, -1, -1):
        s = alpha * out[i] + (1 - alpha) * s
        out[i] = s
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("speaker_track")
    ap.add_argument("out")
    ap.add_argument("--target", default="1080x1920")
    args = ap.parse_args()

    tw, th = (int(x) for x in args.target.lower().split("x"))
    W, H, fps, dur = probe(args.input)

    # Crop window matching the target aspect ratio.
    if W / H > tw / th:
        ch = even(H)
        cw = even(H * tw / th)
    else:
        cw = even(W)
        ch = even(W * th / tw)
    cw, ch = min(cw, even(W)), min(ch, even(H))

    spans = json.load(open(args.speaker_track)).get("spans", [])

    sample_fps = 12.0
    n = max(2, int(dur * sample_fps) + 1)
    cxs, cys = [], []
    last_cx, last_cy = W / 2.0, H / 2.0
    for i in range(n):
        t = i / sample_fps
        box = None
        for s in spans:
            if s["t0"] <= t <= s["t1"] and s.get("speaker_box"):
                box = s["speaker_box"]
                break
        if box:
            last_cx = box["x"] + box["w"] / 2.0
            last_cy = box["y"] + box["h"] / 2.0
        cxs.append(last_cx)
        cys.append(last_cy)

    cxs = smooth(cxs, 0.12)
    cys = smooth(cys, 0.12)

    def clampx(c):
        return int(min(max(c - cw / 2.0, 0), W - cw))

    def clampy(c):
        return int(min(max(c - ch / 2.0, 0), H - ch))

    move_y = ch < H
    cmds = []
    for i in range(n):
        t = i / sample_fps
        line = f"{t:.3f} crop x {clampx(cxs[i])};"
        if move_y:
            line += f" {t:.3f} crop y {clampy(cys[i])};"
        cmds.append(line)

    tmpdir = os.path.dirname(os.path.abspath(args.out)) or "."
    cmd_file = os.path.join(tmpdir, ".reframe.cmds")
    with open(cmd_file, "w") as f:
        f.write("\n".join(cmds) + "\n")

    x0, y0 = clampx(cxs[0]), clampy(cys[0])
    vf = (
        f"sendcmd=f='{cmd_file}',"
        f"crop=w={cw}:h={ch}:x={x0}:y={y0},"
        f"scale={tw}:{th},setsar=1"
    )

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", args.input, "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "copy", "-movflags", "+faststart", args.out],
        check=True,
    )
    os.remove(cmd_file)
    print(f"reframe-vertical: wrote {args.out}  crop {cw}x{ch} -> {tw}x{th}", file=sys.stderr)
    print(args.out)


if __name__ == "__main__":
    main()
