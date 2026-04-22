# shorts

## Deliverable Contract

**Every render-producing bead MUST copy the final artifact to `$HOME/Movies/gastown/shorts/` before `gt done`.**

Polecat worktrees are reaped on `gt done`. A self-validated file inside the worktree is
invisible to the human and dies with the sandbox. Trust in the pipeline requires that
the human can open QuickTime and watch what you produced.

**Naming:** `$HOME/Movies/gastown/shorts/<bead-id>-<timestamp>-<stem>.mp4`

- `<bead-id>` — `BEADS_CURRENT` env var, or regex `sh-[a-z0-9]+` against the current
  git branch name; falls back to timestamp-only if neither is available.
- `<timestamp>` — local `YYYYMMDDTHHMMSS`.
- `<stem>` — output basename (e.g. `smoke`, `short-01`).

**Pipeline enforcement:** `pipeline_v2.py` calls `deliver(out)` after every successful
render (both `--clip-start/--clip-end` smoke mode and full multi-short mode). Any new
render path (future `pipeline_v3.py`, alt renderers) MUST invoke `deliver()` or
replicate the same copy-to-`$HOME/Movies/gastown/shorts/` behaviour.

**Polecat checklist before `gt done` on a render bead:**

1. `ls -la $HOME/Movies/gastown/shorts/` shows the new `.mp4`.
2. File is non-empty (>100KB for a ~30s 9:16 short).
3. You have not overwritten or deleted any pre-existing files there.
