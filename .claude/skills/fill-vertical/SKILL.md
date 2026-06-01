---
name: fill-vertical
description: Reframe a horizontal (16:9) clip to 9:16 (1080x1920) by punching in to FILL the frame — never letterbox, no blur bars. Detects scene cuts and computes ONE static crop box per shot. On multi-face shots it picks the speaker by lip-activity (mouth-openness variance across sampled frames); on no-face shots it crops toward the OpenCV-saliency centroid. Faces are framed ~45% of frame height with the eyeline on the upper third, capped at ~2x upscale. Replaces fit-vertical in the canonical chain.
---

# fill-vertical

Punch-in 9:16 reframe. Fills 1080x1920 on every shot — the "content" look, not the
blurred-letterbox "webinar" look. Runs after `tighten-pace`, before
`chunk-captions`/`burn-subtitles`.

## Usage

```bash
.claude/skills/fill-vertical/fill-vertical.sh <input> <out> \
  [target=1080x1920] [face_frac=0.45] [max_zoom=2.0] [scene_thresh=0.4] [samples=5]
```

- **input** — cut/trimmed/tightened clip (any aspect; designed for 16:9).
- **out** — written 1080x1920 mp4, audio stream-copied, duration unchanged, `+faststart`.

## Contract

- **In:** one video file.
- **Out:** one 1080x1920 mp4. Audio copied from input. Duration preserved.
  Side artifact `<out>.fillplan.json` records per-shot crop boxes.
- **Idempotent:** if `out` is newer than `input`, exits as a cache hit.

## How it works

1. `ffprobe` for source w/h/fps/duration.
2. Scene-cut detect via ffmpeg `select=gt(scene,thresh)` on a downscaled decode → shot list.
3. Per shot: sample `samples` frames, run MediaPipe **FaceLandmarker** (full lip mesh).
   - Link faces across frames by center proximity → tracks.
   - **Speaker = track with max mouth-openness variance.** No measurable lip motion →
     biggest + most-central face. Single face → trivial.
   - Crop box: chosen face ~`face_frac` of frame height, eyeline on the upper third,
     centered on the face, clamped to source bounds, capped at `max_zoom`.
   - **No face →** OpenCV `StaticSaliencyFineGrained`; crop toward the saliency centroid,
     cover-zoom only (no artificial upscale).
4. Render each shot (cut → crop → scale → 1080x1920, video only), concat-demuxer join,
   stream-copy the original audio over the whole clip. Encodes via `_lib/encode.sh`
   (respects its VideoToolbox/thread caps — the CPU-brick fix from shorts-xv5).

## Tunables

| arg | default | meaning |
|-----|---------|---------|
| `target` | 1080x1920 | output WxH |
| `face_frac` | 0.45 | target face height as fraction of frame |
| `max_zoom` | 2.0 | max upscale; past it, accept a smaller-but-sharp face |
| `scene_thresh` | 0.4 | ffmpeg scene-change sensitivity (lower = more cuts) |
| `samples` | 5 | frames sampled per shot for detection (K-frame cap, never per-frame) |

## Deps

`mediapipe`, `opencv-contrib-python`, `numpy` (python3). FaceLandmarker model bundled at
`models/face_landmarker.task`.

## Out of scope

Continuous/tracking pan, split-screen, audio diarization, blur bars/letterbox,
slide-specific handling. Other skills own segment selection, captions, titles, CTA, music.
