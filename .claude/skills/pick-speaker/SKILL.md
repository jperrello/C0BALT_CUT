---
name: pick-speaker
description: For each transcript span, identify which face on screen is the active speaker. Uses face boxes + transcript context + sparse keyframe vision review by Claude. Emits a JSON track of "speaker box per timestamp" suitable for reframe-vertical to follow.
---

# pick-speaker

Active-speaker identification. No audio diarization — we infer the speaker visually (lip movement, face on screen during speech) plus semantic context from the transcript.

## Inputs
- `transcript`: path to `transcribe` output JSON
- `faces`: path to `detect-faces` output JSON
- `video`: source video path (needed for keyframe sampling)
- `out` (optional): output JSON path (defaults to `<video>.speaker.json`)

## Output
```json
{
  "spans": [
    {"t0": 0.42, "t1": 4.10, "speaker_box": {"x": 820, "y": 340, "w": 280, "h": 360}, "confidence": "high"},
    ...
  ]
}
```
One entry per transcript segment. `speaker_box` is the box to follow during that span (interpolated between sampled keyframes).

## How
1. Walk transcript segments.
2. For each segment, gather face boxes that appear in that time window from `faces` JSON.
3. If only one face present → that's the speaker. Done.
4. If multiple faces: sample 2–3 keyframes inside the segment, send them to Claude (host session) along with the transcript text and the face box coordinates, ask "which numbered face is speaking?". Parse the answer.
5. Smooth picks across adjacent segments to avoid jitter.

For batch processing, this skill can be invoked from a `/crew` member to parallelize Claude calls across spans.

## Status
Stub. Implementation: `bd ready`.
