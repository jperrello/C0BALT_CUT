---
name: detect-faces
description: Detect face bounding boxes in a video using MediaPipe, sampled at a target frame rate. Emits a JSON track of boxes per timestamp. Use when downstream skills (pick-speaker, reframe-vertical) need to know where faces are over time.
---

# detect-faces

MediaPipe Face Detector. Boxes only — no identity, no recognition.

## Inputs
- `input`: video path
- `fps` (optional): sampling rate, default `5` (every 200ms)
- `out` (optional): output JSON path (defaults to `<input>.faces.json`)

## Output
```json
{
  "source": "<input>",
  "fps": 5,
  "width": 1920,
  "height": 1080,
  "frames": [
    {"t": 0.0,  "boxes": [{"x": 820, "y": 340, "w": 280, "h": 360, "score": 0.94}]},
    {"t": 0.2,  "boxes": [...]},
    ...
  ]
}
```

## How
1. Open video with OpenCV (`cv2.VideoCapture`).
2. Step at `1/fps` seconds; for each frame run `mediapipe.solutions.face_detection.FaceDetection(min_detection_confidence=0.5)`.
3. Convert relative bbox → absolute pixel coords.
4. Write JSON.

## Run
```
.claude/skills/detect-faces/detect-faces.sh <input> [out] [fps]
```
Defaults: `out=<input>.faces.json`, `fps=5`. Re-running is a no-op when the output mtime is newer than the input.
