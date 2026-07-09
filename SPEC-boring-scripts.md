# SPEC — Boring Scripts (shorts-sgpa)

Cold-start contract for the idea-based selection change in `pick-segments`. Companion to
`SPEC-pick-segments.md` (which stays the engagement-scoring spec); this spec covers only
what shorts-sgpa changed and why.

## Problem

Two selection leaks made scripts boring:

1. **Topic = the atomic unit.** The prompt made topics a HARD CONSTRAINT and
   `parse_reply.py` dropped any cross-topic span unless it was an RLM `thread:true`
   stitch — so a single idea developed at minute 6 and paid off at minute 13 could only
   become one short on RLM sources, framed as a rare exception. The best articulation of
   one point, scattered across a conversation, was structurally unpickable.
2. **The title card carried the hook.** With the title overlay being retired, the first
   SPOKEN sentence alone must stop a scroller in ~1 second — but nothing enforced that;
   weak spoken openers shipped and leaned on on-screen text that will no longer exist.

## The reframe

**Idea = the atomic unit of a short.** A short is ONE coherent idea/throughline. Most
ideas live in one place (single cut — still fine and common). When the same idea is
developed across distant parts of the video, Claude assembles the 2-3 best fragments —
from ANYWHERE in the source, in source-chronological order — into one tight, flowing
conversation. The only hard rule is single-idea coherence: never glue two DIFFERENT
ideas together.

### Enforcement line (the defensible split)

- **Single-cut span** → must sit within one topic (`topic_of` containment /
  ≥70%-dominant-overlap). A raw continuous slice crossing a chapter change is two
  half-ideas — keep that guard.
- **Multi-cut span** → may cross topics freely. Claude has asserted single-idea
  coherence and named it in the required `idea` field (one sentence: the throughline
  all cuts share). Downstream `verify-coherence` already hard-skips multi-cut spans,
  `assemble.py` joins cuts range-agnostically, and `verify-completeness` /
  `director-pass` catch bad stitches.

The RLM `thread:true` mechanism is retained as a *labeled subtype* (its `thread_kind`
metadata still flows through) but is no longer the only cross-topic door — assembly
works on all sources, RLM or not.

## Mandatory 1-second SPOKEN hook

The prompt now states up front: assume NO title card and NO on-screen text — the first
spoken sentence alone must stop a stranger in ~1s (question / provocation / concrete
claim; QUESTION-LEAD ASSEMBLY manufactures a hook when the idea's natural open is slow).
Enforced deterministically in `parse_reply.py`:

- **Hook floor:** picks with `hook_score < PICK_HOOK_FLOOR` (default 5.0) are dropped.
  Never empties the set — if every pick is below floor, the single best-hook span is
  kept with a WARN. Backfilled RLM picks pass by construction (hook_score =
  confidence×10 ≥ 8.5).
- **Payoff budget:** `PAYOFF_BUDGET_SEC` default tightened 3.0 → 2.0 so the turn lands
  ~2s into the delivered open.

## Knobs

| Knob | Default | Effect |
|---|---|---|
| `ASSEMBLE_CROSS_TOPIC` | `1` | `0` = exact rollback: multi-cut cross-topic requires `thread:true` again (legacy behavior). |
| `PICK_HOOK_FLOOR` | `5.0` | Min `hook_score`; below-floor picks dropped (never to empty). `0` disables. |
| `PAYOFF_BUDGET_SEC` | `2.0` | Was 3.0. Seconds the turn may take before the ~2.2 pts/s rank penalty. |

## Output schema additions (`segments.raw.json`)

- `idea` — one sentence naming the single throughline all cuts share (required in the
  prompt; carried by the parser, clamped to 200 chars). For a cross-topic assembly with
  no containing topic, `topic` is set to `idea` so downstream readers stay populated.
- `thread_kind` may now appear on any multi-cut assembly Claude labels, not only RLM
  thread picks.

## Explicitly out of scope

Physically removing `title-transition` from `start.sh`/`shorts.sh`. This change makes
hook selection title-independent NOW; ripping out the title card is a separate one-line
pipeline edit plus a `grade-clip`/`verify-bookends` sweep to drop title assumptions.

## Tests

`.claude/skills/pick-segments/test_assembly.py`: multi-cut cross-topic kept;
single-cut cross-topic dropped; below-floor hook dropped but never to empty; `idea`
carried; `ASSEMBLE_CROSS_TOPIC=0` restores legacy behavior.
