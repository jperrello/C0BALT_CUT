# SELECTION-SUITE — Cross-Lane Implementation Contract

Authoritative coordination doc for implementing `SPEC-selection-suite.md`. The SPEC is the WHAT; this is the HOW + the shared contracts every lane MUST honor so the pieces compose. Read this before writing code. The parent orchestrator owns this file — if a contract here is wrong, report it to the parent, do not freelance.

## Hard rules for every lane

1. **Own ONLY your skill directory.** Each new skill lives at `.claude/skills/<name>/SKILL.md` + `<name>.sh` + helper `.py`. The two mods edit existing skill files in place. These are disjoint — no two lanes touch the same file.
2. **DO NOT edit `start.sh`, `CLAUDE.md`, `.env`, or `.env.example`.** Those are shared and the parent integrates all wiring in ONE pass to avoid concurrent-edit corruption of the canonical entrypoint. Instead, when your skill needs wiring, write `WIRING-<skill>.md` into `.wiring/` (create the dir) describing EXACTLY: (a) where in the per-span / end-of-run chain it slots (which `clip_NN.*` input → output marker), (b) the literal start.sh invocation line, (c) the `.env` knobs + defaults, (d) the CLAUDE.md pipeline-doc sentence(s) to add. Be precise enough that the parent can paste it in.
3. **Idempotent + non-fatal, like every skill here.** mtime+param `.<abbrev>meta` signature cache (see template below). A diagnostic/grading skill must NEVER hard-fail the pipeline — on any error, passthrough or emit a DROSS/empty verdict and exit 0.
4. **Single word names** for vars/functions (project rule). `python3` not `python`. No docstrings describing a file/function. Avoid `else` (early return). Source `.env` for paths, never hardcode.
5. **Self-verify before reporting done:** `bash -n` your script, then RUN it on a REAL artifact (a finished clip under `output/<src>/*.mp4`, or a `work/<id>/clip_NN.*` sidecar) and paste the output JSON proving it works. A skill that has never been executed is not done.

## Canonical input artifacts (verified on disk 2026-06-20)

All per-clip sidecars share the clip's path stem. For a finished short the stem is the `output/<src>/<title>.mp4`; for in-chain it's `work/<id>/clip_NN`. Filenames + real schemas:

| Artifact | Filename | Key fields |
|---|---|---|
| fill-vertical plan | `<stem>.fillplan.json` | `{src:[w,h], target:[w,h], shots:[{t0,t1,kind,crop:[cw,ch,cx,cy]}]}` — `kind` ∈ `"face"`/`"listener"`/`"saliency"`. **shot0 `kind != "face"` is the literal "face-withheld" defect.** Identity clusters are NOT persisted. |
| visual-cadence | `<stem>.cadence.json` | `{pass:bool, duration, threshold, scene, n_changes, max_gap, gap_window:[a,b], changes:[...]}` |
| chunk-captions | `<stem>.chunks.json` | `{source, chunks:[{text, t0, t1, words:[{w,t0,t1}]}]}` |
| broll plan | `<stem>.broll_plan.json` | `{picks:[{t0,t1,...}], ingested_video_ids:[...], vision_calls_used, vision_cap}` — `picks[]` are placement windows. |
| title | `clip_NN.title.txt` | plain text, single line, ≤7-word ALL-CAPS |
| transcript | `clip_NN.transcript.json` / `clip_NN.tight.transcript.json` | `{source, language, words:[{t0,t1,w}], segments:[{t0,t1,text}]}` |
| verify-bookends | `clip_NN.verify.json` | `{action:keep\|trim\|drop, reason, t0?, t1?}` — MOD 2 ADDS `context_pass` + `first_payoff_offset` here. |
| source title | `work/<id>/ingest.json` | `{id,url,title,duration,fps,width,height,path}` |

NOTE for backlog/standalone mode: finished clips in `output/<src>/` may NOT have their sidecars co-located (sidecars live in `work/<id>/`). grade-clip's backlog sweep must (a) read whatever sidecars sit next to the mp4 if present, and (b) degrade gracefully to direct pixel/ffprobe reads (MediaPipe on frame0, silencedetect, edge-variance) when a sidecar is absent. Never crash on a missing sidecar — that is the COMMON case for the 104-clip backlog.

## CONTRACT: `clip_NN.grade.json` (locked — every consumer depends on this)

```json
{
  "clip": "output/<src>/<title>.mp4",
  "grade": 0,                          // int 0-99
  "tier": "GOLD|FIXABLE|DROSS",        // GOLD grade>=GRADE_MIN_UPLOAD(60) & no hard_cap; FIXABLE has hard_cap(s) all in fix_routes; DROSS otherwise
  "hard_caps": ["letterbox","face_withheld","credit_at_open","blocking_card","dead_tail"],  // any present caps grade<=40
  "signals": {
    "frame1_is_face": true,
    "letterbox_bars": false,
    "credit_lit_at_open": false,
    "first_visual_change_sec": 1.2,    // null if none detected
    "first_payoff_offset": 2.4,        // sec until the turn lands; null if unknown
    "longest_static_gap": 3.1,
    "opening_caption_words": 5,
    "max_residual_silence": 0.4,
    "terminal_loop_score": 0.37,       // 0-1 frame1<->lastframe similarity
    "claude": {"hook_payoff":7,"open_loop":6,"cold_context":8}  // absent when GRADE_SKIP_CLAUDE=1
  },
  "fix_routes": ["broll_open_truncate","shot0_repunch","credit_rerender"],  // machine routes fix-cold-open consumes
  "source": "<source-slug>"            // for schedule-drip per-source round-robin
}
```

- `fix_routes` vocabulary (fix-cold-open dispatches on these EXACT strings):
  - `broll_open_truncate` ← a `broll_plan.picks` window overlaps [0, FIXCO_OPEN_GUARD_SEC]
  - `shot0_repunch` ← `fillplan.shots[0].kind != "face"` (face-withheld)
  - `credit_rerender` ← `credit_lit_at_open` (source credit in first ~1s)
  - `card_rerender` ← blocking centered title card instead of top banner
  - `rerun_recommended` ← structural (letterbox = old render; not repairable in place)
- `tier` logic: GOLD = `grade>=GRADE_MIN_UPLOAD && hard_caps empty`. FIXABLE = has `hard_caps` but ALL of them map to a non-`rerun_recommended` fix_route. DROSS = `rerun_recommended` present, or grade < a floor with no clean fix.
- Backlog triage report: `output/_triage.json` = `{generated, n, gold:[clips], fixable:[{clip,defect}], dross:[{clip,reason}], by_source:{...}}`.

## CONTRACT: `topics.scorelist` (schedule-drip owns the file; content locked here)

Plain-text, one rule per line: `<verdict> <regex-or-substring>` where verdict ∈ `GO|HOLD`. Matched case-insensitively against the source-slug + title. Grounded in the 28-day analytics (current_analytics/PIPELINE_TAKEAWAYS.md):

```
# GO — proven or category-aligned winners (science/self-improvement + named entertainment/comedy)
GO huberman
GO neuroscien
GO andrew-huberman
GO rich-roll
GO habit
GO brain
GO dopamine
GO focus
GO discipline
GO caseoh
GO theo-von
GO mrbeast
GO joe-rogan
GO brian-cox
GO mcconaughey
GO pete-davidson
# HOLD — every sub-10-view death clustered here (anchorless generic explainers / dev talks)
HOLD productivity
HOLD tedx
HOLD software-engineer
HOLD aivideo
HOLD how-to-get-things-done
HOLD elite-software
```
Default when no rule matches: `HOLD` (conservative — don't drip an unproven topic into a dark-gap slot ahead of a GO clip, but still schedulable if nothing else fills the day). schedule-drip gates: GO clips fill days first; HOLD clips only backfill a day that would otherwise be dark.

## SKILL template (idempotency + .env + encode/pane libs)

```bash
#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }
input="$1"; out="${input%.*}.<ext>"
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
sig="$(mtime "$input")|${KNOB:-default}|v1"
meta="$out.<abbrev>meta"
[[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]] && { cat "$out"; exit 0; }
# ... compute ...
printf '%s' "$sig" > "$meta"
```
- Claude calls use `_lib/pane.sh` `run_claude_step <step> <prompt> <reply>` (works under `claude -p` standalone AND tmux-pane mode). Shape: `build_prompt.py` → `run_claude_step` → `parse_reply.py` with deterministic fallback. Batch all items into ONE call.
- Encoder args via `_lib/encode.sh` (`vt_args`, `vt_threads`) — never hardcode `-threads 8` (CPU-brick bug shorts-xv5).

## Build order & parent-owned integration
1. grade-clip (deterministic floor first; Claude rubric second, gated by `GRADE_SKIP_CLAUDE`)
2. fix-cold-open (consumes grade.json `fix_routes`)
3. schedule-drip (consumes grade.json + topics.scorelist)
4. pick-segments mod + verify-bookends mod (independent upstream)

Parent integrates all `.wiring/WIRING-*.md` into start.sh/CLAUDE.md/.env after lanes land, then runs the real end-to-end proof: `grade-clip --backlog` over `output/` → `output/_triage.json` → `fix-cold-open` on FIXABLE → `schedule-drip`.
