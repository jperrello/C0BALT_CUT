# pick-segments engagement tuning — Spec

> Cold-start handoff contract. A fresh agent with zero conversation context should be able to make this change from this file alone. It is a **prompt-only** tweak to the existing `pick-segments` skill — no new files, no new deps.

## Working definition
A prompt-only change to the existing `pick-segments` skill so Claude selects the **most engaging** spans — clips a viewer keeps watching. The current prompt (`build_prompt.py:82-93`) already scores `hook_score`/`structure_score`/`overall_score` and rewards concrete nouns; this sharpens the *definition of engaging* by naming additional positive cues (energy/affect, back-and-forth dialogue, concrete specificity) for Claude to weigh holistically. It is **not** a multi-speaker preference, **not** new score fields, **not** a Python signal/diarization step, **not** a change to ranking, filtering, topic, duration, or filler logic.

## Who uses it and how
Unchanged. `shorts.sh` / `start.sh` invoke `pick-segments.sh <transcript.json> [out] [n] [dmin] [dmax] [topics.json]` in the same pipeline slot. Same inputs (transcript, RMS sparkline, optional topics), same `segments.json` output shape. Idempotent mtime cache unchanged.

## Core features
- **Engagement is the sole objective.** The prompt's framing shifts from "clip-worthy spans" to "the spans a viewer is least likely to scroll past and most likely to finish."
- **Name engagement cues, don't weight them.** The prompt lists positive signals — high vocal energy/affect (excitement, laughter, emphasis), lively back-and-forth exchange, concrete/specific nouns and stakes — as *examples of what tends to be engaging*, folded into Claude's holistic `overall_score`. No per-trait scores, no composite, no required trait.
- **Tie energy cues to the data Claude already has.** Direct Claude to read the existing 60-bin RMS sparkline as an affect signal — favor spans whose time range sits over energy peaks (laughter, raised voices), not flat valleys.
- **Everything else stays.** Filler hard-reject (`parse_reply.py:32-58`), topic-boundary enforcement, duration/overlap validation, `n`-cap, rank-by-`overall_score` (`parse_reply.py:95`) — all unchanged.

## Rules and edge cases
- **Mostly-solo source** → no penalty. Engagement is judged on its own terms; a gripping monologue outranks a dull exchange. No multi-speaker weighting exists to starve picks.
- **Output schema unchanged** → still `{t0, t1, rationale, title_suggestion, hook_score, structure_score, overall_score}`. No new fields.
- **`parse_reply.py` untouched** unless the schema changes — it won't.
- **No new tunables/flags.** Engagement emphasis lives in the prompt text, not in CLI args.

## Look and feel
N/A (backend prompt change). Observable effect: picks skew toward higher-energy, more specific, more dynamic moments; fewer flat, abstract, low-stakes spans.

## Resolved decisions

### Objective
Choice: Engagement is the only target; multi-speaker/affect/concreteness are unweighted cues.
Why: user — "No weight on this, only thing that matters is engaging clips." The upstream note framed it as "favor multi-speaker," but the user explicitly demoted that to a non-goal; dialogue is a *symptom* of an engaging clip, not the aim.

### Signal source
Choice: Pure prompt inference — Claude infers from transcript text + the existing RMS sparkline. No Python extraction, no diarization.
Why: user picked "Pure prompt inference." Accepts that Claude can't hear speaker identity and judges from text + global energy only. Diarization was grounded and rejected: pyannote on CPU is ~2-3 min per audio-minute + 4-8GB RAM (would risk the `shorts-xv5` CPU-brick), and audio diarization is already a rejected stack decision (see `SPEC-fill-vertical.md`).

### Score model
Choice: Steer `overall_score` via prompt guidance; no new fields, no weighted composite, no logging.
Why: user — "I don't care about logging or having control, it wastes time and tokens, just pick the clips." Smallest change, fewest added instructions.

## Technical constraints
- **Single file changes:** edit the prompt string in `build_prompt.py` (the `SCROLL-STOP HOOK` block, lines 82-93). `parse_reply.py`, `pick-segments.sh`, `rms.py` unchanged.
- **No new deps, no API key, no CPU cost** beyond what's already spent.
- **Instruction budget:** keep added guidance tight — adherence degrades past ~150-200 instructions per Dex Horthy, *Advanced Context Engineering for Agents* / *No Vibes Allowed* (2026) `[from mcptube transcripts]`. Fold cues into the existing scoring block rather than adding a new section.

## Out of scope
Diarization (any library); Python-computed affect/dialogue/concreteness signals; new JSON score fields; weighted composites or tunable weights; logging; per-span RMS computation; changes to filler/topic/duration/ranking logic; any downstream skill.

## Decisions to double-check
1. **Demoting multi-speaker to a non-goal** contradicts the original upstream task wording ("tune scoring to favor multi-speaker… spans"). Followed the user's later, explicit correction. Flag in case the upstream author expected an actual dialogue bias.
2. **Pure prompt inference can't truly detect energy/affect** — Claude maps a span to global sparkline bins by eye. If picks still feel flat on a real clip, the cheapest fix is feeding per-span mean-RMS as one number (a small, contained follow-up), without going to diarization.
