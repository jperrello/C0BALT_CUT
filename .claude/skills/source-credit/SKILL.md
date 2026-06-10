---
name: source-credit
description: Overlay a persistent "Original video: <title>" credit near the TOP of a finished short. Reads the source title from work/<id>/ingest.json and renders it as a transparent PNG via PIL; ffmpeg composites it for the whole clip duration. Positioned at the top so it sits above the captions (lower third) and clear of the centered title card. Runs after title-transition and before loudnorm in the per-span chain.
allowed-tools: Bash
user-invocable: true
---

# source-credit

Persistent attribution overlay. "Original video:" in blue (#1E90FF), the
source video's title in white, baked in at the same vertical band as a TV
chyron. Same renderer pattern as `burn-subtitles` / `title-transition`
(PIL PNG, ffmpeg overlay) because the local ffmpeg has no libass/drawtext.

## Invoke

```
.claude/skills/source-credit/source-credit.sh <input> <ingest.json> <out>
```

- `input`: video to overlay onto (any aspect ratio; designed for 1080x1920)
- `ingest.json`: source video metadata (reads `title`)
- `out`: output mp4

## Output

mp4, same dimensions and duration as the input, video re-encoded, audio
stream-copied. Cache: `<out>.scmeta` records the title signature; rebuild
only when `input` or title changes. Prints the output path to stdout.

## Geometry

Banner is positioned with its top at y = 4% of frame height. For a
1080x1920 short this puts the credit around y=77 (a top chyron). Captions
now live in the lower third (≈y=1344) and the title card pops in centered,
so the credit collides with neither. Font auto-fits from 58pt down to 38pt
(2pt smaller than the prior 60→40 range). Banner width auto-fits to the
title; long titles wrap to a second line.
