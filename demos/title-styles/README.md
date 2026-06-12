# title-style prototypes

Demo renderer for the five title-transition styles now shipped in
`.claude/skills/title-transition/` (the `news` prototype was cut after review).
Each style is matched to a genre of short and has its own synthesized SFX
(stdlib `wave`, no external assets), rendered as PIL PNG frame sequences (the
local ffmpeg has no drawtext) composited over a real captioned intermediate
clip.

## Styles

| # | style | genre | animation | SFX |
|---|---|---|---|---|
| 1 | `slam` | hype / beast-style | title slams from 3.4x down to place, squash settle, flash + screen shake on land | riser into deep boom |
| 2 | `typewriter` | true crime / storytelling | Courier chars type in with blinking block cursor, background dims | per-key clicks + end ding |
| 3 | `glitch` | tech / AI | RGB-split flicker + slice displacement in, mid-hold re-hit, glitch out | bitcrush zaps + static crackle |
| 4 | `bounce` | comedy | words pop in one-by-one with elastic overshoot + wobble rotation | rising pops per word + boing |
| 5 | `cinematic` | documentary | Didot serif tracks in from wide letter-spacing, sapphire rule draws out, background dims | airy swell into sub thump |

All styles keep the brand language where it fits: Sapphire Glow `#2E6BFF`
accent word, black-stroked type, Platinum white.

## Render

```
bash demos/title-styles/demo.sh [base_clip] [seconds]
```

Outputs land in `demos/title-styles/out/`: one `NN_<style>.mp4` per style plus
`00_ALL_STYLES_REEL.mp4` (all five back-to-back). Each demo has a corner tag
identifying the style.

`demo.sh` drives the skill's own generators
(`.claude/skills/title-transition/{styles.py,sfx.py}`) so the demos always
match production. In the real pipeline, `pick-title-styles` assigns each span
a style and `title-transition` renders it.
