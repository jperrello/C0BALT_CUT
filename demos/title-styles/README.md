# title-style prototypes

Six candidate title-transition styles, each matched to a genre of short and each
with its own synthesized SFX (stdlib `wave`, no external assets). Rendered as
PIL PNG frame sequences (the local ffmpeg has no drawtext) composited over a
real captioned intermediate clip.

## Styles

| # | style | genre | animation | SFX |
|---|---|---|---|---|
| 1 | `slam` | hype / beast-style | title slams from 3.4x down to place, squash settle, flash + screen shake on land | riser into deep boom |
| 2 | `typewriter` | true crime / storytelling | Courier chars type in with blinking block cursor, background dims | per-key clicks + end ding |
| 3 | `glitch` | tech / AI | RGB-split flicker + slice displacement in, mid-hold re-hit, glitch out | bitcrush zaps + static crackle |
| 4 | `bounce` | comedy | words pop in one-by-one with elastic overshoot + wobble rotation | rising pops per word + boing |
| 5 | `news` | commentary / breaking | carbon bar with sapphire trim slides in, text wipes on, slides out | whoosh in/out + 3-tone ident |
| 6 | `cinematic` | documentary | Didot serif tracks in from wide letter-spacing, sapphire rule draws out, background dims | airy swell into sub thump |

All styles keep the brand language where it fits: Sapphire Glow `#2E6BFF`
accent word, black-stroked type, Platinum white.

## Render

```
bash demos/title-styles/demo.sh [base_clip] [seconds]
```

Outputs land in `demos/title-styles/out/`: one `NN_<style>.mp4` per style plus
`00_ALL_STYLES_REEL.mp4` (all six back-to-back). Each demo has a corner tag
identifying the style.

## Files

- `styles.py` — renders one style's full-frame RGBA PNG sequence + `events.json`
  (SFX cue list) + corner `label.png`
- `sfx.py` — synthesizes `sfx.wav` from `events.json`
- `demo.sh` — drives both, composites with ffmpeg (overlay + amix + limiter),
  builds the reel

Promotion path: a chosen style becomes a `style` argument on the
`title-transition` skill (frame-sequence overlay replaces the single-PNG
scale expression), with its SFX mixed under the clip audio at the cue times.
