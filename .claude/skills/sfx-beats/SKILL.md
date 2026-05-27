---
name: sfx-beats
description: Mix synthesized riser/hit/stinger SFX into a short at detected tension peaks. Riser ends at the first pivot word ('but'/'therefore'/'so'/etc.) inside the middle 60% of the clip, a low impact hit lands at the loudest RMS-per-second peak after it, a soft outro stinger sits in the last 0.4s. All SFX synthesized with stdlib `wave` — no external assets.
allowed-tools: Bash
user-invocable: true
---

# sfx-beats

Sound design is emotional manipulation, not decoration. This skill places three
SFX events on a finished clip's audio bed:

1. **Riser** (0.8s noise sweep up + pitched sweep) — ends *exactly* on the first
   pivot word in the transcript that falls inside the middle 60% of the clip.
   Pivots: `but`, `therefore`, `so`, `because`, `however`, `then`, `actually`.
2. **Hit** (50–80Hz transient, ~0.22s) — at the highest RMS-per-second peak
   strictly after the riser end.
3. **Stinger** (440/660Hz bell, ~0.45s decay) — sits in the last 0.4s.

If no pivot word lands in the middle 60%, the riser+hit are skipped (low
confidence) and only the stinger plays. All three are mixed at ~-18 dBFS so
they sit under the speech bed; an `alimiter` keeps peaks ≤ 0.97.

## Invoke

```
.claude/skills/sfx-beats/sfx-beats.sh <input> <transcript.json> <out> [audio_rms.json]
```

- `input`: video path (any aspect; designed for finished shorts)
- `transcript.json`: word-timed transcript (from `transcribe`)
- `out`: output video path
- `audio_rms.json` (optional): per-second RMS energy. If omitted, computed
  on the fly via `pick-segments/rms.py`.

## Output

mp4 with video stream-copied (no re-encode) and audio re-encoded to AAC 192k
after `amix` with the synthesized SFX bed. Prints the output path to stdout.
Idempotent via `<out>.sfxmeta` (input + transcript mtimes).

## How

- `plan_sfx.py` scans the transcript for the earliest pivot word in the middle
  60% of the clip and picks the RMS peak after it from `audio_rms.json`.
- `make_sfx.py` renders one full-length stereo WAV with all three events placed
  at the planned timestamps. Pure stdlib `wave`, same pattern as
  `title-transition/make_sfx.py`. Riser pans L→R; the hit is centered; the
  stinger is centered and slightly attenuated.
- `sfx-beats.sh` `amix`es the SFX bed over the source audio.

## Status

Implemented — verified on `work/883ad50ade/clip_03.final.mp4` (riser placed at
the word `actually`, hit on the post-pivot RMS peak, stinger in the last 0.4s).
