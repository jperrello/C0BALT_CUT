---
name: title-transition
description: Overlay an animated, SFX-backed title card on the opening of a short. Five styles matched to clip register — slam (hype), typewriter (true crime), glitch (tech), bounce (comedy), cinematic (documentary) — each a PIL frame sequence with synthesized sound effects mixed under the clip audio. Style comes from pick-title-styles' per-span title_style (default slam).
allowed-tools: Bash
user-invocable: true
---

# title-transition

Animated intro title card for a short. The style of the animation (and its
sound) is chosen per span by `pick-title-styles`; the title text comes from
`generate-title` (third-person, ≤7 words, ALL CAPS).

## Invoke

```
.claude/skills/title-transition/title-transition.sh <input> <title> <out> [style=slam] [dur=auto]
```

- `input`: video path (designed for finished 9:16 shorts)
- `title`: title text — rendered UPPERCASE, auto-wrapped to ≤2 lines
- `style`: `slam` | `typewriter` | `glitch` | `bounce` | `cinematic`
  (unknown values warn and fall back to `slam`)
- `dur`: total card duration in seconds; `auto` uses the style's native length
  (slam 2.2, typewriter 3.0, glitch 2.4, bounce 2.4, cinematic 3.2)

## Styles

| style | genre | animation | SFX |
|---|---|---|---|
| `slam` | hype / beast-style | slams from 3.4x to place, squash settle, flash + screen shake on land | riser into deep boom |
| `typewriter` | true crime / story | Courier chars type in, blinking block cursor, background dims | per-key clicks + end ding |
| `glitch` | tech / AI | RGB-split flicker + slice displacement in, mid-hold re-hit, glitch out | bitcrush zaps + static |
| `bounce` | comedy | words pop in one-by-one, elastic overshoot + wobble | rising pops + boing |
| `cinematic` | documentary | Didot serif tracks in from wide letter-spacing, sapphire rule draws out, background dims | airy swell into sub thump |

All styles keep the brand language where it fits: Sapphire Glow `#2E6BFF`
accent word, black-stroked type, Platinum white (`brand/BRAND.md`).

## How

The local ffmpeg has no drawtext/libass, so:

1. `styles.py` renders the animation as a full-frame transparent PNG sequence
   (30fps) plus `events.json`, the SFX cue list (every keystroke, the slam
   landing, each word pop...).
2. `sfx.py` synthesizes `sfx.wav` from the cues — stdlib `wave` only, no
   external assets.
3. `title-transition.sh` composites: per-style background treatment (shake +
   flash for slam, ramped dim for typewriter/cinematic) → frame-sequence
   overlay → `amix` of clip audio + SFX through `alimiter` (no clipping
   against pre-loudnorm speech).

Background effects apply BEFORE the overlay so the card itself never shakes,
flashes, or dims. Runs before `loudnorm`, so SFX get leveled with the speech.

## Output

mp4, same dimensions and duration as the input. Idempotent: `<out>.ttmeta`
records `title|style|dur`; cache hit requires `out` newer than `input` and a
matching signature, so changing title OR style re-renders.

Demo all five styles on any clip: `bash demos/title-styles/demo.sh <clip>`.
