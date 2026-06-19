---
name: switch-faces
description: Hard-cut to a non-speaking listener's reaction shot at speech pauses — the "react" cutaway a real editor inserts while the speaker breathes. Deterministic, no Claude: detects a second face in the 16:9 source (reusing fill-vertical's face/identity clustering), picks the biggest speech-pause beats, and crops that listener's face into 1080x1920 for a ~0.8-1.2s hold before returning to the speaker. Timeline-preserving (audio copied, duration identical) so downstream timestamps stay valid. Runs on the clean vertical AFTER zoom-punch and BEFORE broll/captions. Solo talking-heads (no second face) pass through untouched. SWITCH_FACES=0 disables.
allowed-tools: Bash
user-invocable: true
---

# switch-faces

When two people share a frame (or a multicam podcast), a real editor cuts away to
the *listener* reacting while the speaker talks — it manufactures "multi-cam"
energy and breaks up a static two-shot. This skill does it deterministically: it
finds the non-dominant face in the 16:9 source and hard-cuts to a 1080x1920 crop
of it during the speaker's natural pauses.

It is the reaction-shot sibling of `zoom-punch` (re-zooms the *speaker* at loud
words) and `jump-cut` (reframes the *same* speaker on a tiling rhythm). All three
are deterministic, timeline-preserving lap passes on the clean vertical.

## Invoke

```
.claude/skills/switch-faces/switch-faces.sh <base_vert.mp4> <source16x9.mp4> <transcript.json> <out.mp4>
```

- `base_vert.mp4`: the 1080x1920 vertical clip to composite onto (post zoom-punch)
- `source16x9.mp4`: the pre-vertical 16:9 source (`clip_NN.tight.mp4` / the verify-bookends recut) — holds the listener's face, cropped out of the vertical
- `transcript.json`: the clip-local word-timed transcript (same timeline as the vertical — fill/jump/zoom are all timeline-preserving)

## Placement rules

- needs **≥2 face identities** in the source (dominant speaker + a listener); solo clips → passthrough
- listener = a non-dominant face per shot, the **calmest** (least lip motion) one — reads as listening, not a second speaker
- windows = the biggest inter-word **pauses** (`SWITCH_MIN_PAUSE`, default 0.32s), biggest first; window starts ~0.4s before the gap so the cut catches the speaker landing the line
- hold = ~0.8-1.2s (cycles 1.1/0.9/1.0/0.8), count = clamp(dur/12, 1, 4), ≥5s apart
- excludes the cold-open title region (first `SWITCH_LEAD`=2.8s) and last `SWITCH_TAIL`=1.5s
- a window must lie **inside one shot** with the listener present for its whole span — never straddles a shot cut
- listener framed a touch looser (`SWITCH_FACE_FRAC`=0.40) than fill-vertical's speaker (0.45)

## Chain position

After `zoom-punch`, BEFORE `broll-pick`/`broll-composite` (b-roll cutaways may
still override their own windows) and `burn-subtitles` (captions burn on top of
the reaction shot). Timeline-preserving — audio is stream-copied and total
duration is identical, so every downstream timestamp stays valid. Orchestrators
treat it as non-fatal: on any failure the vertical passes through. Disable with
`SWITCH_FACES=0`.

## Output

1080x1920 mp4, video re-encoded, audio stream-copied. Idempotent via
`<out>.sfmeta`. No listener / no pause windows → passthrough copy.
