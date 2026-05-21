---
name: reframe-vertical
description: Crop a horizontal video to 9:16 vertical, tracking the active speaker. Takes a speaker-box track from pick-speaker and renders a smooth pan-crop with ffmpeg. Use to fit horizontal source into vertical short format.
---

# reframe-vertical

Single-panel speaker-tracked vertical crop. No PiP, no screen-share tiling — just keep the speaker in frame.

## Inputs
- `input`: video path
- `speaker_track`: path to `pick-speaker` output JSON
- `out`: output video path
- `target` (optional): output resolution, default `1080x1920`

## Output
9:16 mp4 with the speaker centered. Same audio, same duration.

## How
1. Compute crop window per frame: target a 9:16 box centered on the current `speaker_box`, clamped to source frame.
2. Smooth crop centers across frames (one-euro filter or simple low-pass) — no more than ~5px/frame movement.
3. Emit ffmpeg `crop=W:H:x:y` filter with `sendcmd` time-varying expressions, OR pre-render a sidecar `.cmds` file and use `ffmpeg -filter_complex`.
4. Run ffmpeg, scaling to target resolution.

## Status
Implemented — `reframe-vertical.sh` / `reframe_vertical.py`. Crop centers are smoothed with a forward/backward exponential filter and driven through ffmpeg `sendcmd` (the crop filter exposes `x`/`y` as runtime commands).
