---
name: fit-vertical
description: Reframe a horizontal (YouTube 16:9) video to a 9:16 shorts aspect ratio with no face tracking. Whole video is kept and centered; top/bottom are filled with a blurred zoomed copy. Use when you just need the aspect ratio adjusted, not a speaker-following crop.
---

# fit-vertical

Aspect-ratio-only reframe. No facial tracking, no cropping of content — the entire
source frame is preserved, centered, and the empty top/bottom are filled with a
blurred zoomed copy of the same video.

This is the simple counterpart to `reframe-vertical`, which requires a
`pick-speaker` track. Reach for `fit-vertical` when the source has no single
speaker to follow (b-roll, gameplay, slideshows, multi-person) or when you just
want the original framing intact.

## Inputs
- `input`: video path (any aspect ratio)
- `out`: output video path
- `target` (optional): output resolution `WxH`, default `1080x1920`
- `blur_sigma` (optional): background gaussian blur strength, default `20`

## Output
`target`-resolution mp4 (9:16). Same audio (stream-copied), same duration.

## How
One ffmpeg pass with `-filter_complex`:
1. `split` the source into a background and foreground copy.
2. Background: `scale=force_original_aspect_ratio=increase` + `crop` to cover the
   full frame, then `gblur`.
3. Foreground: `scale=force_original_aspect_ratio=decrease` to fit inside the
   frame untouched.
4. `overlay` the foreground centered on the blurred background.

Video is re-encoded libx264 veryfast crf18 (yuv420p); audio is stream-copied.
Idempotent via output-vs-input mtime check.

## Usage
```bash
.claude/skills/fit-vertical/fit-vertical.sh <input> <out> [target=1080x1920] [blur_sigma=20]
```

## Status
Implemented — `fit-vertical.sh`.
