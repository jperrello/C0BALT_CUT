#!/usr/bin/env python3
import argparse, json, os, sys
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision


HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL = os.path.join(HERE, "blaze_face_short_range.tflite")


def run(input_path, fps, out_path, model_path):
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"detect-faces: cannot open {input_path}", file=sys.stderr)
        sys.exit(2)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / src_fps if src_fps else 0

    opts = mp_vision.FaceDetectorOptions(
        base_options=mp_python.BaseOptions(model_asset_path=model_path),
        running_mode=mp_vision.RunningMode.VIDEO,
        min_detection_confidence=0.5,
    )
    detector = mp_vision.FaceDetector.create_from_options(opts)

    step = 1.0 / fps
    frames = []
    t = 0.0
    while t <= duration + 1e-6:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = detector.detect_for_video(mp_image, int(t * 1000))
        boxes = []
        for d in res.detections or []:
            bb = d.bounding_box
            score = d.categories[0].score if d.categories else 0.0
            boxes.append({
                "x": max(0, int(bb.origin_x)),
                "y": max(0, int(bb.origin_y)),
                "w": max(0, int(bb.width)),
                "h": max(0, int(bb.height)),
                "score": float(score),
            })
        frames.append({"t": round(t, 3), "boxes": boxes})
        t += step

    cap.release()
    detector.close()

    out = {
        "source": os.path.abspath(input_path),
        "fps": fps,
        "width": width,
        "height": height,
        "duration": round(duration, 3),
        "frames": frames,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    n_with = sum(1 for fr in frames if fr["boxes"])
    print(f"detect-faces: wrote {out_path} ({len(frames)} frames, {n_with} with faces)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()
    out = args.out or (args.input + ".faces.json")

    if not os.path.exists(args.model):
        print(f"detect-faces: model not found: {args.model}", file=sys.stderr)
        sys.exit(2)

    if os.path.exists(out):
        in_mtime = os.path.getmtime(args.input)
        out_mtime = os.path.getmtime(out)
        if out_mtime >= in_mtime:
            print(f"detect-faces: cache hit at {out}", file=sys.stderr)
            return
    run(args.input, args.fps, out, args.model)


if __name__ == "__main__":
    main()
