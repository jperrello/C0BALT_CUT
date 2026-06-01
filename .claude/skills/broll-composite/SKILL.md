---
name: broll-composite
description: Hard-cut full-frame B-roll cutaways onto a 1080x1920 clip per broll_plan.json. During each [t0,t1] the entire frame is replaced by the cutaway (instant in/out, no crossfade/zoom); 16:9 source is scale-to-cover + center-cropped to 1080x1920 with no bars. Podcast audio is stream-copied; video re-encoded. Zero valid picks -> passthrough copy. Pure ffmpeg.
allowed-tools: Bash
user-invocable: true
---

# broll-composite

Applies the cutaways chosen by broll-pick. For each pick `[t0,t1]` the whole
1080×1920 frame is replaced by the B-roll (hard cut, no transition). The 16:9
source is scaled to COVER and center-cropped to 1080×1920 — full-bleed, never
letterboxed (same philosophy as fill-vertical). The podcast audio stream is
copied untouched for the whole clip; B-roll audio is dropped. Runs BEFORE
burn-subtitles so karaoke captions render on top of the cutaways.

## Invoke

```
.claude/skills/broll-composite/broll-composite.sh <in_clip.mp4> <broll_plan.json> <out.mp4>
```

- `in_clip`: the vertical 1080×1920 clip (from fill-vertical)
- `broll_plan.json`: from broll-pick
- `out`: composited clip

## Behavior

- Zero picks, or every `clip_path` missing → copy-passthrough, exit 0.
- A pick whose `clip_path` no longer exists is skipped; remaining picks apply.
- ffmpeg failure → falls back to passthrough (never blocks the pipeline).

## Idempotency

Caches on in_clip+plan mtimes via `<out>.compmeta`.

## Notes

- Center-cover crop is self-contained here. If fill-vertical later exposes a
  reusable saliency-crop helper, switch to it for consistent framing.
- Whole video is re-encoded (overlay can't partial stream-copy); audio is
  `-c:a copy`. Uses `_lib/encode.sh` (VideoToolbox/x264) + thread caps.
