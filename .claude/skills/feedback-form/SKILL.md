---
name: feedback-form
description: Drop a stage-mapped scored feedback form (*.feedback.md) next to a rendered short in ./output so the user can grade topic, hook, title, captions, b-roll, music, pacing, and an overall post/rework/kill verdict. Each section is keyed to the pipeline skills that own it, so a low score routes straight to the stage that caused it. Run per short after save-local, or in --scan mode over the whole output dir.
---

# feedback-form

Generates the fill-in form the user grades each short with. The form is the
input half of the feedback loop; `feedback-ingest` is the output half.

## Inputs
- `short`: path to a saved short, e.g. `output/<source>/<name>.mp4`
- `clip` (optional): work-dir clip prefix, e.g. `work/<id>/clip_01`. When
  given, the form is pre-filled with `clip_01.title.txt` and
  `clip_01.mood.txt` so the user sees what the pipeline chose.
- `--scan [root]`: instead of one short, walk `root` (default `./output`)
  and generate a form for every mp4 missing one.

## Output
`output/<source>/<name>.feedback.md` next to the short. Never overwrites an
existing form (a filled form is user data).

## Form contract
- Frontmatter: source, short, title, mood, generated, reviewed.
- One `## <key>` section per gradeable property: topic, hook, title,
  captions, broll, music, pacing, overall. Each carries an
  `<!-- owns: skill, skill -->` comment naming the pipeline stages that
  control that property.
- Per section: `score:` 1-5 (blank = no opinion) and `why:` free text.
  `## overall` uses `verdict:` (post / rework / kill) instead of a score.
- A form counts as reviewed only when the user sets `reviewed:` to a date.

## How
1. `feedback-form.sh <short.mp4> [clip-prefix]` or `feedback-form.sh --scan`.
2. The pipeline should call this right after `save-local` for each short,
   passing the work clip prefix so title/mood are pre-filled.

## Status
Implemented — `feedback-form.sh` + `form.py`.
