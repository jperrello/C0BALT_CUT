---
name: pick-segments
description: Pick N clip-worthy spans from a transcript. Claude reads the full transcript plus a per-second RMS energy summary and returns time ranges suitable for shorts. Replaces the old keyword/hook-word heuristic ranker.
---

# pick-segments

Claude-driven segment selection. No heuristics — Claude judges what's clip-worthy.

## Inputs
- `transcript`: path to `transcribe` output JSON
- `audio_rms` (optional): path to a per-second RMS energy JSON (computed inline if missing)
- `topics` (optional): path to a `segment-topics` output JSON. Auto-discovered as `topics.json` next to the transcript. When present, every picked span is required to lie entirely within one topic — spans that straddle a topic boundary are dropped. This is what prevents shorts that jump between unrelated subjects.
- `n`: number of shorts to pick, default `5`
- `duration` (optional): target duration range, default `[20, 60]` seconds
- `out` (optional): output JSON path

## Output
```json
{
  "shorts": [
    {
      "t0": 124.8,
      "t1": 156.3,
      "rationale": "Strong reaction shot followed by punchline — laughter at 152s.",
      "title_suggestion": "When the bit finally lands"
    },
    ...
  ]
}
```

## How
1. Compute audio RMS at 1Hz from the source video (ffmpeg → wave → numpy) if not provided.
2. Build a compact context: transcript text with timestamps every line, RMS energy summary (peaks + valleys).
3. Send to Claude with the instruction "pick N spans in [min, max] seconds that would make compelling shorts. Return JSON with t0, t1, rationale, title suggestion."
4. Validate ranges (non-overlap, duration bounds), write JSON.

For batch / large transcripts, a `/crew` member can be spawned to keep this off the host session.

## Status
Stub. Implementation: `bd ready`.
