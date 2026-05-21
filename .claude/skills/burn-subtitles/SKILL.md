---
name: burn-subtitles
description: Burn karaoke-style word-timed subtitles into a video. Takes a transcript JSON with word timestamps and a video, emits a new video with subtitles rendered in. Renders text as a PNG overlay sequence (the local ffmpeg build has no libass/drawtext).
allowed-tools: Bash
user-invocable: true
---

# burn-subtitles

Word-timed subtitle burn-in for shorts. Highlights the current word, no manual sync.

## Invoke

```
.claude/skills/burn-subtitles/burn-subtitles.sh <input> <transcript.json> <out> [style] [font_size]
```

- `input`: video path
- `transcript`: path to `transcribe` output JSON (`words[]` + `segments[]`)
- `out`: output video path
- `style` (optional): `line` | `word-karaoke` | `selective`, default `word-karaoke`
- `font_size` (optional): default `72`

## Output

mp4 with subtitles burned in. Same dimensions, audio stream-copied. Prints the
output path to stdout. Idempotent: skips work if `out` is newer than both inputs.

## Styles

- `line`: one plain line per transcript segment.
- `word-karaoke`: words grouped (gap > 0.6s or 6 words), the active word is
  highlighted in accent yellow as playback advances.
- `selective`: only burns segments overlapping high-RMS-energy seconds
  (z-score > 1.0); falls back to burning all segments if none are hot.

## How

The local ffmpeg build ships without `libass`, `subtitles`, or `drawtext`
filters. So `burn_subtitles.py` renders a transparent PNG per video frame with
PIL (Arial Bold, white text + black stroke, lower third, 9:16-safe margins),
hardlinking duplicate frames for speed. `burn-subtitles.sh` then composites the
sequence onto the source with ffmpeg's `overlay` filter and re-encodes video
(libx264 veryfast crf18); audio is copied.

## Status

Works. Tested on a 6.7s 720x1280 clip (say-synthesized speech, 19 words):
- word-karaoke: 20 unique states, frame at t=3.2s shows 16130 white + 5616
  accent (highlighted-word) pixels in the lower third.
- line: 27049 white pixels, 0 accent. Dimensions and duration preserved,
  audio stream-copied (aac).
