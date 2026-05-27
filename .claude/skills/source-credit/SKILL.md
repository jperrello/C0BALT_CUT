---
name: source-credit
description: Overlay a persistent "Original video: <title>" credit in the bottom third of a finished short. Reads the source title from work/<id>/ingest.json and renders it as a transparent PNG via PIL; ffmpeg composites it for the whole clip duration. Positioned high enough in the lower band that it never overlaps the like-subscribe-overlay CTA banner. Runs after title-transition and before loudnorm in the per-span chain.
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

Banner is positioned with its baseline at y = 70% of frame height. For a
1080x1920 short this puts the credit around y=1340. The CTA banner
(`like-subscribe-overlay`) sits in the lower ~12% margin (≈y=1690+), so the
two never collide. Banner width auto-fits to the title; long titles wrap
to a second line.
