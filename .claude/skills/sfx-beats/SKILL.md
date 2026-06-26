---
name: sfx-beats
description: Mix synthesized SFX into a short. Two modes — comedy (CANONICAL, runs after burn-subtitles in the pipeline): Claude marks punchline/irony beats and a vine boom / record scratch lands on each; tension (on request only): riser ending at the first pivot word, low hit at the loudest RMS peak after it, soft outro stinger. All SFX synthesized with stdlib `wave` — no external assets. Comedy mode marks ZERO beats on non-comedic clips and passes through untouched.
allowed-tools: Bash
user-invocable: true
---

# sfx-beats

Sound design is emotional manipulation, not decoration. Two modes:

## comedy (canonical — in the per-span chain after burn-subtitles)

Claude reads the clip transcript and marks 0-4 beats where a meme SFX
amplifies the moment:

1. **boom** (vine boom, ~0.8s saturated 90→40Hz sub drop, LOUD on purpose) —
   a punchline, absurd claim, or savage line landing.
2. **scratch** (record scratch, ~0.32s back-and-forth filtered noise) — a
   wait-WHAT irony pivot.

The "ding" insight/aha-moment bell is RETIRED — comedy mode marks only
punchline (boom) and irony (scratch) beats.

The prompt is explicitly conservative: a boom on a mediocre beat reads as
cringe, so ZERO beats is a valid answer → passthrough copy. Beats are
validated (known types, ≥2.5s apart, inside [1.0, dur-0.5], max 4). Any
Claude/parse failure degrades to passthrough — never fatal. `SFX_COMEDY=0`
skips the step in the orchestrators.

## tension (on request only — NOT in the canonical chain)

1. **Riser** (0.8s noise sweep) — ends exactly on the first pivot word
   (`but`/`therefore`/`so`/...) inside the middle 60% of the clip.
2. **Hit** (50–80Hz transient) — at the highest RMS peak after the riser.
3. **Stinger** (440/660Hz bell) — in the last 0.4s.

Tension SFX sit at ~-18dBFS under speech; comedy booms run hotter (~-7dB peak)
because the boom IS the joke. An `alimiter` keeps the mix ≤0.97.

## Invoke

```
.claude/skills/sfx-beats/sfx-beats.sh <input> <transcript.json> <out> [mode=tension|comedy] [audio_rms.json] [--pane <tmux>]
```

- `mode`: `tension` (default) or `comedy`
- `audio_rms.json` (tension only): per-second RMS; computed on the fly if omitted
- `--pane`: route the comedy Claude call through a long-lived tmux pane

## Output

mp4 with video stream-copied and audio AAC 192k after `amix` with the SFX bed
(or a passthrough copy when nothing is marked). Idempotent via `<out>.sfxmeta`
(input + transcript mtimes + mode).

## How

- comedy: `comedy_prompt.py` → `run_claude_step` → `parse_comedy.py` →
  `make_sfx.py` renders the marked events into a full-length stereo WAV.
- tension: `plan_sfx.py` picks pivot/peak deterministically → same renderer.
