---
name: feedback-ingest
description: Turn the user's filled *.feedback.md forms into the standing taste file the pipeline reads. Parses every reviewed form under ./output into feedback/history.jsonl, then distills the why-text into taste.md, the per-stage guidance that generate-title, pick-mood, pick-segments, and broll-pick apply on future runs. Run whenever the user says they have filled in feedback.
---

# feedback-ingest

The output half of the feedback loop. `feedback-form` drops the forms; this
skill harvests them and compounds the feedback into `taste.md`.

## Inputs
- Filled forms under `./output/**/*.feedback.md`. Only forms whose
  frontmatter `reviewed:` field is set count; blank forms are skipped.

## Outputs
- `feedback/history.jsonl`: one record per reviewed form (rebuilt from all
  forms on every run, so re-editing a form just works). Fields: frontmatter
  plus `sections` (`{key: {score, why, verdict}}`) and `form` path.
- `taste.md` at repo root: the distilled standing guidance.

## How
1. Run `feedback-ingest.sh` (deterministic parse, rebuilds history.jsonl).
2. Read `feedback/history.jsonl` and rewrite `taste.md` (Claude step, host
   session, no API key). Distillation rules:
   - One `## <key>` section per form section: topic, hook, title, captions,
     broll, music, pacing, overall. Same keys as the form, exactly.
   - Bullets only, max 5 per section. Each bullet is one imperative,
     generalized instruction ("prefer X", "never Y"), not a quote of the
     feedback. Generalize from the why-text, not the bare scores.
   - Newest feedback wins: drop or rewrite any bullet a newer record
     contradicts.
   - A pattern needs support: one-off complaints about a single clip stay
     out unless scored 1 or 5 with a clear why. Recurring themes go in.
   - Never invent guidance with no record behind it.

## taste.md contract (what downstream skills parse)
```
## title
- <bullet>
- <bullet>

## music
- <bullet>
```
`generate-title` injects `## title`, `pick-mood` injects `## music`,
`pick-segments` injects `## topic` + `## hook` into their prompts when
`./taste.md` exists. `broll-pick` reads `## broll` per its SKILL.md.
Section bodies are free markdown bullets; keep them short, they land
verbatim inside prompts.

## Status
Implemented — `feedback-ingest.sh` + `ingest.py` (parse); distillation is a
Claude step per the rules above.
