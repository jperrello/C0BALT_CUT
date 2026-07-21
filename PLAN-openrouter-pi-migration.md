# PLAN: Claude → OpenRouter models + pi agent

Plan only. Sources: live OpenRouter catalog (2026-07-21) + pi-mono docs (badlogic).

## Call sites (all via `_lib/pane.sh::run_claude_step` or the `rlm-segment-subcall` Task agent)

- **A — cheap structured text:** segment-topics, derive-thesis, verify-coherence, bookend-trim, verify-completeness, trim-filler, chunk-captions, generate-title, pick-mood, sfx-beats, broll-pick anchors.
- **B — quality-critical text:** pick-segments, RLM MAP subcalls, RLM REDUCE, grade-clip rubric.
- **C — vision (contact sheets/frames):** verify-bookends, broll-pick verify, director-pass, first-span-feedback, profile-clip, style-gate.

## Model tiers ($/1M tokens in/out)

| Tier | Model | $ | ctx | Notes |
|---|---|---|---|---|
| DEFAULT (A+C) | `qwen/qwen3.5-flash-02-23` | 0.065 / 0.26 | 1M | text+image+video — one model covers text AND vision |
| QUALITY (B) | `minimax/minimax-m2.5` | 0.15 / 0.90 | 204K | pick-segments + RLM |
| Text alts | `deepseek/deepseek-v4-flash` 0.09/0.19 · `z-ai/glm-4.7-flash` 0.06/0.40 | | | |
| Vision alt | `google/gemini-2.5-flash-lite` | 0.10 / 0.40 | 1M | if qwen vision verdicts are noisy |
| Escalation | `deepseek/deepseek-v4-pro` 0.43/0.87 (text, 1M) · `qwen/qwen3-vl-235b-a22b-instruct` 0.21/1.90 (vision) | | | |
| FREE | `:free` variants (gpt-oss-120b, nemotron-3-super) | 0 | | prompt dev only, rate-limited |

Rejected: anthropic/openai/kimi flagships (20-30× cost). `gpt-5-mini` (0.25/2.00) = tier-B fallback if Chinese-lab routing is unacceptable.

**Cost:** ~15 source calls + ~10/span ⇒ **$0.05–0.15 per source video**.

## pi migration

pi facts: `pi -p "…"` = print mode (stdin merged into prompt); `--mode json` for events/token usage; `--model provider/id --api-key`; OpenRouter as OpenAI-compatible provider in `~/.pi/agent/models.json`; vision via `@file.png`; `--session <id>` / `--no-session`.

1. **`.env`** — `OPENROUTER_API_KEY`, `PI_BIN`, `MODEL_DEFAULT` / `MODEL_QUALITY` / `MODEL_VISION`. Skills read tier via env.
2. **`_lib/pane.sh`** (the choke point) — `run_claude_step` → `run_llm_step <step> <prompt> <reply> [tier]`: `pi -p --no-session --model $m < prompt > reply`. Pane path: run `pi -p` inside the pane per dispatch (keep `in.txt`/`out.txt`/`out.done`); drop pooled-pane `/clear` — no warm session needed. Add `run_llm_vision_step` passing `@image` args.
3. **Tier C skills** — swap to `run_llm_vision_step` + `MODEL_VISION`; prompts unchanged; existing `parse_reply.py` fallbacks guard weak models.
4. **`rlm-segment-subcall`** — Task agent → direct `pi -p --model $MODEL_QUALITY @chunk_NN.txt`; `--mode json` gives real token counts for `usage.json`. `RLM_SUBCALL_MODEL` becomes an OpenRouter id.
5. **`start.sh` / `shorts.sh`** — pane bootstrap `claude` → `pi`; drop pooling complexity.
6. **`autopilot.sh`** — GUI-login requirement GONE (API key works headless/locked).
7. **fsf / style-gate fixers** — interactive `pi --session` with QUALITY model; gate logic unchanged.
8. **CLAUDE.md** — rewrite "No Anthropic API key" section; mcptube `discover` stays forbidden by default (revisit).
9. Crew/ralph (`~/.claude`) — out of scope, follow-up.

## Rollout

1. Land `run_llm_step` behind `LLM_BACKEND=claude|pi` (default claude).
2. Tier A on pi; full-source run; diff grades vs Claude baseline (`grade-clip` + `_selection.json` = oracle).
3. Tier C; eyeball broll accepts + director verdicts.
4. Tier B last (quality-determining); A/B before flipping.
5. Flip default; update autopilot docs.

## Risks

- Malformed JSON from cheap models → one retry-with-error, then existing deterministic fallbacks.
- Vision quality drop → escalate `MODEL_VISION` only.
- OpenRouter provider variance → pin `provider.order` in models.json.
- Prompts tuned on Claude → one tuning pass per tier (test seams make it cheap).

## Operator decisions

- Chinese-lab routing OK? No ⇒ gemini-2.5-flash-lite (A/C) + gpt-5-mini (B), ~2-3× cost.
- Collapse pooled panes to per-dispatch `pi -p`? (recommended)
- Un-forbid `mcptube discover`?
