---
name: broll-composite
description: Pure ffmpeg overlay of a broll_plan.json onto a finished clip. Reads {t0,t1,clip_path,...} entries from broll-pick's output and scales each clip to 1080x520, letterboxed, into the bottom blurred bar at y=1332 during its [t0,t1] window. No Claude calls. Idempotent via <out>.compmeta keyed on input + plan mtimes.
allowed-tools: Bash
user-invocable: true
---

# broll-composite

The compositing half of the split-out broll skill. Pure ffmpeg — no Claude.
Reads `broll_plan.json` from `broll-pick` and renders the overlays. Safe to
run in parallel with other rendering passes; cheap to re-run.

## Invoke

```
.claude/skills/broll-composite/broll-composite.sh <input> <broll_plan.json> <out>
```

- `input`: the clip to overlay onto (post-loudnorm in the canonical chain).
- `broll_plan.json`: output of `broll-pick`.
- `out`: output mp4 path.

If the plan has zero picks (or every `clip_path` is missing), the input is
copy-passthrough and the skill exits 0.

## Output

mp4 with audio stream-copied and video re-encoded only over the overlay
windows. Same layout as the legacy `broll` skill: bottom blurred bar at
`y=1332`, size 1080x520, 16:9 letterboxed. Idempotent via `<out>.compmeta`
(input + plan mtimes).

## Status

Split-out from the legacy `broll` skill per May26-spec §2. Pair with
`broll-pick` upstream.
