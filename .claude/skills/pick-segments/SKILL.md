---
name: pick-segments
description: Pick N clip-worthy spans from a transcript. Claude reads the full transcript plus a per-second RMS energy summary and returns the most engaging time ranges for shorts. Each span carries `cuts` — 1-3 non-contiguous source ranges within ONE topic, assembled into a tighter story (skip the sag, keep hook→payoff); a single-cut span is just `cuts:[[t0,t1]]`. Replaces the old keyword/hook-word heuristic ranker.
---

# pick-segments

Claude-driven segment selection. No heuristics — Claude judges what's clip-worthy.

## Inputs
- `transcript`: path to `transcribe` output JSON
- `audio_rms` (optional): path to a per-second RMS energy JSON (computed inline if missing)
- `topics` (optional): path to a `segment-topics` output JSON. Auto-discovered as `topics.json` next to the transcript. When present, every picked span is required to lie entirely within one topic — spans that straddle a topic boundary are dropped. This is what prevents shorts that jump between unrelated subjects.
- `heatmap` (auto-discovered): YouTube most-replayed data from `ingest`. This is a weak discovery hint and tie-breaker, not a selection mandate.
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
      "cuts": [[124.8, 156.3]],
      "rationale": "Strong reaction shot followed by punchline — laughter at 152s.",
      "title_suggestion": "When the bit finally lands",
      "hook_score": 8,
      "context_score": 9,
      "structure_score": 8,
      "overall_score": 8.5,
      "replay_quotient": 1.2
    },
    ...
  ]
}
```

## How
1. Compute audio RMS at 1Hz from the source video (ffmpeg → wave → numpy) if not provided.
2. Build a compact context: transcript text with timestamps every line, RMS energy summary, optional replay heatmap, and topic boundaries.
3. Ask Claude for complete standalone story arcs. The hierarchy is cold-viewer context first, hook second, replay/RMS only as supporting evidence.
4. Validate ranges (non-overlap, duration bounds, topic containment, filler openings), add a small replay tie-breaker, write JSON.

For batch / large transcripts, a `/crew` member can be spawned to keep this off the host session.

## ADVICE_CORPUS toggle (experimental, default OFF — epic shorts-dwt)
`ADVICE_CORPUS=1` prepends the versioned §9 entertainment-advice corpus (`advice.md`) to the
picker prompt; unset/`0` emits today's prompt byte-for-byte. The corpus lives in its own file so
it is A/B-able independently of code. Whether it actually improves clip SELECTION is being
measured non-circularly (no Claude in the scorer) per `tools/eval/PRE-REGISTRATION.md`; it ships
as default only after a CI-clean Tier-2 win. The invariant "OFF = verbatim, ON = OFF + corpus and
nothing else" is locked by `test_advice_toggle.py`. (Later extend the same gate to
`rlm-segment-subcall`.)

## Status
Stub. Implementation: `bd ready`.
