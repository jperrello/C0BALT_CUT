# shorts

## Deliverable Contract

**Every render-producing bead MUST copy the final artifact to
`/Users/jperr/Documents/shorts/delivered/` before the bead is closed.**

Trust in the pipeline requires that the human can open QuickTime and watch what you
produced. The delivery dir is an **absolute path** so every render lands in one stable
place the user can browse.

**Naming:** `/Users/jperr/Documents/shorts/delivered/<bead-id>-<timestamp>-<stem>.mp4`

- `<bead-id>` — `BEADS_CURRENT` env var, or regex `sh-[a-z0-9]+` against the current
  git branch name; falls back to timestamp-only if neither is available.
- `<timestamp>` — local `YYYYMMDDTHHMMSS`.
- `<stem>` — output basename (e.g. `smoke`, `short-01`).

**Pipeline enforcement:** `pipeline_v2.py` calls `deliver(out)` after every successful
render (both `--clip-start/--clip-end` smoke mode and full multi-short mode). Any new
render path (future `pipeline_v3.py`, alt renderers) MUST invoke `deliver()` or
replicate the same copy-to-`delivered/` behaviour.

**Render-bead checklist before close:**

1. `ls -la /Users/jperr/Documents/shorts/delivered/` shows the new `.mp4`.
2. File is non-empty (>100KB for a ~30s 9:16 short).
3. You have not overwritten or deleted any pre-existing files there.

## Crew workflow (per CONTEXT.md D-07)

No worktrees, no per-bead branches — everything commits straight to `main`. The
loop for a working bead is:

1. **Bead** — pick up an open bead matching your lane (`surface=` label).
2. **in_progress** — `bd update <id> --status in_progress` before writing code.
3. **Commit to main** — small focused commit on `main`, scoped to the bead.
4. **Brutus smoke** — render-shipping beads route through `brutus` for the
   smoke-clip + delivery-contract check (D-10).
5. **Close** — `bd close <id>` once brutus signs off.

Crew members coordinate by `surface` so two in-progress beads do not share a
file region. `delivered/` is append-only — the crew never deletes from it.
