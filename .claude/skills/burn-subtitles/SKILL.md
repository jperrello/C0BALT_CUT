---
name: burn-subtitles
description: Burn karaoke-style word-timed subtitles into a video. Takes a transcript JSON with word timestamps and a video, emits a new video with subtitles rendered in. Uses ASS format + ffmpeg.
---

# burn-subtitles

Word-timed subtitle burn-in for shorts. Highlights current word, no manual sync.

## Inputs
- `input`: video path
- `transcript`: path to `transcribe` output JSON
- `out`: output video path
- `style` (optional): `line` | `word-karaoke` | `selective`, default `word-karaoke`
- `font_size` (optional): default `72`

## Output
mp4 with subtitles burned in. Same dimensions, same audio.

## How
1. Read words[] from transcript.
2. Generate ASS subtitle file:
   - `line`: one line per transcript segment, plain.
   - `word-karaoke`: per-word `\k<centisec>` tags so the active word highlights.
   - `selective`: only burn for spans with high RMS energy / Claude-flagged moments.
3. Place subs in the lower third with safe margins for 9:16.
4. Run ffmpeg with `subtitles=<ass>` filter.

## Status
Stub. ASS templating logic salvageable from `archive/pre-pivot:pipeline_v2.py:339-512`.
