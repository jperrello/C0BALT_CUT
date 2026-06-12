---
name: pick-title-styles
description: Assign a title-transition style (slam/typewriter/glitch/bounce/cinematic) to every picked span in ONE batched Claude call. Fit wins — the span's content and emotional register pick the style — with variety as the tiebreak: joint assignment spreads styles across the run (no style on more than half the spans) and a rolling .recent log softly biases against styles overused in past runs. Writes title_style + title_style_note into each span. Never fails: any Claude/parse failure degrades to a deterministic least-recently-used round-robin.
allowed-tools: Bash
user-invocable: true
---

# pick-title-styles

Batched per-run style assignment for the `title-transition` intro cards. Runs
once in the analysis phase (after verify-coherence snapshots `segments.json`),
so the per-span lanes just read their span's `title_style` later.

## Invoke

```
.claude/skills/pick-title-styles/pick-title-styles.sh <segments.json> <transcript.json> <out.json> [--pane <tmux>]
```

`out.json` may be the same path as `segments.json` (updated in place via tmp).

## How it picks

One Claude call sees ALL spans (topic, rationale, transcript excerpt) plus the
style menu with genre guidance:

| style | register |
|---|---|
| slam | hype, stunts, reveals, shock, money |
| typewriter | mystery, true-crime, secrets, story setups |
| glitch | tech, AI, internet culture, disruption |
| bounce | comedy, absurd anecdotes, playful |
| cinematic | reflective, profound, life advice |

Rules in the prompt, in priority order: (1) fit wins — strongly-typed spans get
their obvious style even if recently used; (2) when fit is comparable, spread
across the run; (3) hard cap: no style on more than ceil(N/2) spans; (4) soft
recency bias from `.recent` (last 15 picks across runs, gitignored, summarized
into the prompt).

## Fallbacks

- Claude step fails → empty reply → parse assigns every span the least-used
  style (usage = this run + `.recent` history; ties break in menu order).
- Reply parses but misses/garbles a span → that span gets the least-used pick.
- The skill never exits non-zero for semantic failures; orchestrators treat it
  as best-effort and `title-transition` defaults to `slam` if the field is
  absent entirely (e.g. resumed pre-feature runs).

## Idempotence

Skips (cache hit) when every span already has `title_style` — mtime is useless
here since out may BE the segments file. `.recent` is only appended on a real
(non-cached) pick pass.
