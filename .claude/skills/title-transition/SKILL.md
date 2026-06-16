---
name: title-transition
description: Animate the title as a COLD OPEN in the TOP banner over the live opening footage — no blocking center card, no SFX — held until TITLE_SWAP (default 2.0s) so brand-overlays can hand off to the source citation in the same slot. Frame 1 stays content (a face mid-sentence) to protect the swipe-rate / "Stayed to Watch" signal. Five styles matched to clip register — slam (hype), typewriter (true crime), glitch (tech), bounce (comedy), cinematic (documentary) — each a PIL frame sequence anchored at TITLE_ANCHOR_FRAC (default 0.135). Style comes from pick-title-styles' per-span title_style (default slam).
allowed-tools: Bash
user-invocable: true
---

# title-transition

Animated COLD-OPEN title for a short. The title animates in the TOP banner zone
OVER the live opening footage — never a blocking center card — so frame 1 stays
content (a face mid-sentence), protecting the swipe-rate / "Stayed to Watch"
signal. The style is chosen per span by `pick-title-styles`; the title text
comes from `generate-title` (third-person, ≤7 words, ALL CAPS). The title holds
until `TITLE_SWAP` and clears via its own fade-out, then `brand-overlays` fades
the source citation into the same top slot (see that skill).

## Invoke

```
.claude/skills/title-transition/title-transition.sh <input> <title> <out> [style=slam] [dur=auto]
```

- `input`: video path (designed for finished 9:16 shorts)
- `title`: title text — rendered UPPERCASE, auto-wrapped to ≤2 lines
- `style`: `slam` | `typewriter` | `glitch` | `bounce` | `cinematic`
  (unknown values warn and fall back to `slam`)
- `dur`: title lifetime in seconds; `auto` uses `TITLE_SWAP` (default 2.0) so
  the title has fully cleared the top banner by the citation hand-off
- env `TITLE_SWAP` (default 2.0) — hold / hand-off point, shared with
  brand-overlays + source-credit
- env `TITLE_ANCHOR_FRAC` (default 0.135) — vertical center of the title block
  as a fraction of height (the top-banner zone). 0.5 restores the centered look
  for demos.

## Styles

| style | genre | animation |
|---|---|---|
| `slam` | hype / beast-style | punches from 2.6x to place, squash settle |
| `typewriter` | true crime / story | Courier chars type in, blinking block cursor |
| `glitch` | tech / AI | RGB-split flicker + slice displacement in, mid-hold re-hit, glitch out |
| `bounce` | comedy | words pop in one-by-one, elastic overshoot + wobble |
| `cinematic` | documentary | Didot serif tracks in from wide letter-spacing, sapphire rule draws out |

All styles keep the brand language where it fits: Sapphire Glow `#2E6BFF`
accent word, black-stroked type, Platinum white (`brand/BRAND.md`). NO SFX (the
card-era riser/boom/clicks are retired) and NO full-frame bg treatment (the old
flash/shake/dim shook the live shot). `events.json`/`sfx.py` remain in-tree but
unused by the cold-open path.

## How

The local ffmpeg has no drawtext/libass, so `styles.py` renders the animation
as a full-frame transparent PNG sequence (30fps), anchored at
`TITLE_ANCHOR_FRAC`. `title-transition.sh` overlays it directly on the live
footage (no bg treatment) and stream-copies the clip audio (no SFX mix).

## Output

mp4, same dimensions and duration as the input. Idempotent: `<out>.ttmeta`
records `title|style|dur|top<anchor>`; cache hit requires `out` newer than
`input` and a matching signature, so changing title, style, or anchor
re-renders.

Demo all five styles on any clip: `bash demos/title-styles/demo.sh <clip>`.
