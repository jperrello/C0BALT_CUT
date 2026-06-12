---
name: zoom-punch
description: Quick punch-in zooms at a clip's loudest words — the standard retention-edit emphasis beat. Deterministic, no Claude: per-second RMS peaks snapped to word starts pick 1-4 punch moments (4s+ apart, clear of the title card and the tail); each gets a ~0.6s 10% zoom pulse (fast attack, hold, smooth release) cropped toward the upper third so the eyeline holds. Runs on the 1080x1920 vertical clip BEFORE broll-composite and burn-subtitles so cutaways and captions never warp.
allowed-tools: Bash
user-invocable: true
---

# zoom-punch

A punch-in zoom is the cheapest "wake up" beat in shorts editing: a sharp ~10%
zoom punctuating an emphasis word. This skill places 1–4 of them
deterministically.

## Invoke

```
.claude/skills/zoom-punch/zoom-punch.sh <in.mp4> <transcript.json> <out.mp4> [strength=0.10]
```

- `in.mp4`: the 1080x1920 vertical clip (post fill-vertical)
- `transcript.json`: the clip-local word-timed transcript
- `strength`: zoom amount (0.10 = 10% punch)

## Placement rules

- candidate = loudest per-second RMS buckets (`pick-segments/rms.py`)
- snapped to the nearest word start within 0.6s — the punch lands ON a word
- first 2.8s excluded (title card) and last 2s excluded
- min 4s apart, count = clamp(dur/12, 1, 4)
- pulse: 0.1s attack -> ~0.35s hold -> 0.18s release, upper-third crop bias

## Chain position

After `fill-vertical`, BEFORE `broll-composite` (cutaways replace the full
frame and must not be warped by a punch) and `burn-subtitles` (captions must
not wobble). Orchestrators treat it as non-fatal: on failure the vertical clip
passes through unzoomed. Disable with `ZOOM_PUNCH=0`.

## Output

1080x1920 mp4, video re-encoded, audio stream-copied. Idempotent via
`<out>.zpmeta`. No punch candidates -> passthrough copy.
