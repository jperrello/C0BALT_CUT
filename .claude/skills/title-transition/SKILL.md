---
name: title-transition
description: Overlay an animated title card on the opening of a short. The title pops in at center with an overshoot scale, lands with a white flash + screen shake, holds, then scales back down to nothing. Use as a hook-grabbing intro after the clip is otherwise finished.
allowed-tools: Bash
user-invocable: true
---

# title-transition

Animated intro title card for a short. A brief title describing the clip flies
in, holds, and flies out silently. Overlaid on the clip's opening seconds, so
total duration is unchanged and no title-card sound effect is added.

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

- **Pop in** (first `min(0.45, dur/3)`s): card scales up at center — from 0.3×
  → ~1.07× → 1.0× via a **back-out (Penner) ease** on the scale factor.
  Overshoots by ~7% on the landing frame then settles. Reads as the title
  punching into place from the center of the frame (no side travel).
- **Hold** (the middle): card sits at full scale, centered horizontally and
  vertically.
- **Pop out** (last `min(0.45, dur/3)`s): card scales back down to 0 with an
  ease-in (`p^1.5`).

## Impact effects (locked to the landing frame, t = `fly`)

The instant the title lands is the visual beat. Two visual effects fire together:

1. **White flash** — 70ms brightness pulse on the underlying clip (`eq=brightness`
   ramps 0.38 → 0). The title is overlaid AFTER the flash, so the text stays
   crisp while the background brightens.
2. **Screen shake** — 150ms damped sinusoid: ±9px horizontal, ±5px vertical,
   applied via a `pad`+`crop` window on the source video. Decays to zero by the
   end of the window. The title is overlaid AFTER the shake, so the text stays
   readable while the background "kicks".
The card is rendered as bare text (no panel, no border) in Impact, ALL CAPS,
white with one sapphire-accented keyword (`#2E6BFF`) and a thick black stroke for
legibility — the exact same visual language as `burn-subtitles`' caption
preset so the title and the captions read as one brand.

Title text is supplied by the `generate-title` skill (third-person, ≤7 words,
ALL CAPS). `pick-segments` no longer emits a `title_suggestion` — call
`generate-title` per clip and pass its output here.

## How

The local ffmpeg build has no `drawtext`/`libass`. So:

1. `render_title.py` renders the title as one tight transparent PNG banner with
   PIL (Arial Bold, auto-sized, rounded panel).
2. `title-transition.sh` overlays the PNG with an `overlay` filter whose scale is
   time-varying, `enable`d only for `[0, dur]`, and preserves the source audio
   unchanged apart from AAC re-encoding when an audio stream exists.

## Status

Implemented — `title-transition.sh`, `render_title.py`.
