---
name: title-transition
description: Overlay an animated title card on the opening of a short. A brief title slides in from the left, holds centered, then slides out the right with a synthesized whoosh. Use as a hook-grabbing intro after the clip is otherwise finished.
allowed-tools: Bash
user-invocable: true
---

# title-transition

Animated intro title card for a short. A brief title describing the clip flies
in, holds, flies out — with a whoosh. Overlaid on the clip's opening seconds, so
total duration is unchanged.

## Invoke

```
.claude/skills/title-transition/title-transition.sh <input> <title> <out> [dur] [font_size]
```

- `input`: video path (any aspect ratio; designed for finished 9:16 shorts)
- `title`: the title text — kept brief, rendered UPPERCASE, auto-wrapped to ≤2 lines
- `out`: output video path
- `dur` (optional): total animation duration in seconds, default `2.5`
- `font_size` (optional): `auto` (default) fits the largest size that holds ≤2
  lines; or pass an integer pixel size

The `pick-segments` skill already emits a `title_suggestion` per span — feed that
in as `title`.

## Output

mp4, same dimensions and duration as the input, video re-encoded (libx264
veryfast crf18), audio re-encoded to AAC 192k. Prints the output path to stdout.
Idempotent: a `<out>.ttmeta` sidecar records `title|dur|font`; a cache hit
requires `out` newer than `input` *and* a matching signature, so changing the
title re-renders.

## Animation

- **Slide in** (first `min(0.45, dur/3)`s): card enters from off the left edge,
  ease-out cubic, settles centered.
- **Hold** (the middle): card sits centered, vertically mid-frame.
- **Slide out** (last `min(0.45, dur/3)`s): card exits off the right edge,
  ease-in cubic.

The card is rendered as bare text (no panel, no border) in Impact, ALL CAPS,
white with one cyan-accented keyword (`#00E5FF`) and a thick black stroke for
legibility — the exact same visual language as `burn-subtitles`' caption
preset so the title and the captions read as one brand.

Title text is supplied by the `generate-title` skill (third-person, ≤7 words,
ALL CAPS). `pick-segments` no longer emits a `title_suggestion` — call
`generate-title` per clip and pass its output here.

## How

The local ffmpeg build has no `drawtext`/`libass`. So:

1. `render_title.py` renders the title as one tight transparent PNG banner with
   PIL (Arial Bold, auto-sized, rounded panel).
2. `make_sfx.py` synthesizes the sound bed as a stdlib-`wave` WAV — a rising
   whoosh (one-pole-lowpass-filtered noise, brightening sweep) under the
   slide-in, a soft low impact at the landing, a falling whoosh under the
   slide-out. Whooshes pan left→right to track the motion.
3. `title-transition.sh` overlays the PNG with an `overlay` filter whose `x` is a
   time-varying eased expression, `enable`d only for `[0, dur]`, and mixes the
   SFX over the source audio (`amix … normalize=0` + `alimiter`). If the source
   has no audio stream, the SFX becomes the audio track.

## Status

Implemented — `title-transition.sh`, `render_title.py`, `make_sfx.py`.
