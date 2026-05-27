---
name: like-subscribe-overlay
description: Overlay a JS-rendered like/subscribe button animation on the last ~4 seconds of a finished short. The animation source is cta.html (HTML+CSS+JS driving cursor moves, click punches, bell ring, thumb fill); build-cta.sh renders it frame-by-frame via headless Chromium (Playwright, omitBackground) and ffmpeg-encodes to assets/cta.mov (ProRes 4444 with alpha). Runs as the final visual step before save-local.
allowed-tools: Bash
user-invocable: true
---

# like-subscribe-overlay

Closes a short with a hook-grabbing call to action. A JS-driven like/subscribe
button animation plays in the lower third over the last `dur` seconds:
cursor enters → clicks SUBSCRIBE (red → gray, scale punch, expanding ring) →
bell rings → cursor glides left to the thumbs-up → clicks LIKE (thumb fills
blue, scale punch, expanding ring) → holds the final state.

The animation is authored in plain HTML+CSS+JS (`cta.html`) and pre-rendered
once into a transparent ProRes 4444 `.mov` asset (`assets/cta.mov`). Runtime
just composites that asset.

## Invoke

```
.claude/skills/like-subscribe-overlay/like-subscribe-overlay.sh <input> <out> [dur=4.0]
```

- `input`: finished short (any aspect ratio; designed for 1080x1920)
- `out`: output mp4
- `dur`: total CTA duration in seconds (clamped to clip length, default 4.0)

## Output

mp4, same dimensions and duration as the input, video re-encoded
(libx264 veryfast crf18), audio re-encoded to AAC 192k. Prints the output
path to stdout. Idempotent: a `<out>.lsmeta` sidecar records the signature;
a cache hit requires `out` newer than `input` *and* a matching signature.

## Animation

- **Slide up** (first `min(0.5, dur/4)`s): banner enters from below the
  frame, ease-out cubic, settles in the lower third (~12% margin from
  bottom).
- **Hold** (the middle): banner sits centered horizontally, lower third.
- **Slide down** (last `min(0.5, dur/4)`s): banner exits below the frame,
  ease-in cubic.

The banner is rendered with PIL: Impact font, white with cyan accent on
`SUBSCRIBE`, thick black stroke — same visual language as
`title-transition` and `burn-subtitles`. Icons (thumbs-up + bell) are
synthesized polygons, not external assets. SFX is a synthesized two-note
bell ding written with stdlib `wave`.

## Where in the pipeline

Runs after `loudnorm` and before `bg-music` / `save-local`.

## How

The local ffmpeg build has no `drawtext`/`libass`, so:

1. `render_cta.py` renders the banner as one tight transparent PNG with
   PIL (text + synthesized thumbs-up + bell).
2. `make_sfx.py` synthesizes a soft two-note bell ding as a stdlib-`wave`
   WAV — one ding on the slide-in landing, a quieter accent mid-hold.
3. `like-subscribe-overlay.sh` overlays the PNG with an `overlay` filter
   whose `y` is a time-varying eased expression, `enable`d only for
   `[start, start+dur]`, and mixes the SFX (timed with `-itsoffset start`)
   over the source audio (`amix … normalize=0` + `alimiter`).
