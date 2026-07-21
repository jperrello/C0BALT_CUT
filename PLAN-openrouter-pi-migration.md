# PLAN: Migrate off Claude → OpenRouter models + pi agent

Status: PLAN ONLY — no code changed yet.
Scraped from the live OpenRouter catalog (`https://openrouter.ai/api/v1/models`, 342 models, 2026-07-21) and the pi coding agent docs (badlogic/pi-mono).

## Goal

1. Replace every Claude call in the pipeline with an OpenRouter-routed model, tiered by what each step actually needs, at minimum cost.
2. Replace the `claude` CLI / tmux-pane dispatch layer with **pi** (`@mariozechner/pi-coding-agent`), which speaks OpenRouter natively.

## 1. Where the pipeline calls an LLM today

All dispatch goes through `_lib/pane.sh::run_claude_step` (either `claude -p --output-format text` or a long-lived interactive tmux Claude pane), plus one Task-subagent path (`rlm-segment-subcall`). Call sites, grouped by what they actually require:

**A. Cheap structured text (JSON in → JSON out, no vision, low reasoning):**
segment-topics (single-prompt path), derive-thesis, verify-coherence, bookend-trim, verify-completeness, trim-filler, chunk-captions, generate-title, pick-mood, sfx-beats (comedy beats), broll-pick anchor picking, name-short is deterministic (no LLM).

**B. Quality-critical text (the judgment that determines short quality):**
pick-segments (span scoring/assembly), RLM MAP subcalls (`rlm-segment-subcall`, currently Sonnet), RLM REDUCE/synthesis, grade-clip Claude rubric (when enabled).

**C. Vision (contact sheets / frame grids as images):**
verify-bookends (head/tail 1.5s frames), broll-pick batched vision verify, fix-cold-open (none — deterministic), director-pass (12-frame contact sheet), first-span-feedback reviewer, profile-clip judgment fields, style-gate re-review.

## 2. Model picks (OpenRouter, live pricing per 1M tokens)

| Tier | Model | $ in / out | ctx | Why |
|---|---|---|---|---|
| **DEFAULT (A + most C)** | `qwen/qwen3.5-flash-02-23` | 0.065 / 0.26 | 1M | Cheapest capable model that does text+image+video — ONE model covers both the structured-JSON steps and the contact-sheet vision steps, so pane pooling stays simple |
| **Text alt** | `deepseek/deepseek-v4-flash` | 0.09 / 0.19 | 1M | Slightly better long-transcript behavior, text-only; good for segment-topics/RLM MAP if qwen underperforms |
| **Text alt 2** | `z-ai/glm-4.7-flash` | 0.06 / 0.40 | 200K | Backup workhorse |
| **Vision alt** | `google/gemini-2.5-flash-lite` | 0.10 / 0.40 | 1M | Most reliable cheap vision (frames + audio/video native); use if qwen vision verdicts are noisy on broll verify / director-pass |
| **QUALITY (B)** | `minimax/minimax-m2.5` | 0.15 / 0.90 | 204K | Strong reasoning at bargain price for pick-segments + RLM REDUCE |
| **Quality alt** | `deepseek/deepseek-v4-pro` | 0.43 / 0.87 | 1M | If pick-segments quality regresses on m2.5; 1M ctx fits a full 2h transcript un-chunked |
| **Quality vision** | `qwen/qwen3-vl-235b-a22b-instruct` | 0.21 / 1.90 | 131K | Escalation target for director-pass / first-span-feedback if the cheap tier misses defects |
| **FREE (experiments)** | `openai/gpt-oss-120b:free`-class `:free` models, `nvidia/nemotron-3-super-120b-a12b:free` | 0 / 0 | — | Rate-limited; fine for dev iterations of prompts, never for production runs |

Rejected: all `anthropic/*` (Sonnet 5 is $2/$10 — 20-30× the default tier), `openai/gpt-5.1` ($1.25/$10), `moonshotai/kimi-k3` ($3/$15). `openai/gpt-5-mini` ($0.25/$2) is a reasonable quality-tier fallback if Chinese-lab routing is a concern.

**Cost ballpark per source video** (2h podcast, 5 spans): ~15 source-level calls + ~10 calls/span, dominated by pick-segments (~80K in) and RLM MAPs (~15K in × 12 chunks). At default+quality tiers ≈ **$0.05–0.15/video**. Even 10 videos/day ≈ $1.50/day worst case.

## 3. pi agent migration (the dispatch layer)

pi facts that matter (from pi-mono docs):
- `pi -p "prompt"` = print mode, direct text out (drop-in for `claude -p --output-format text`); reads stdin and merges it into the prompt; `--mode json` for JSONL events.
- `--provider` / `--model provider/id` / `--api-key` per invocation; OpenRouter configured as an OpenAI-compatible provider in `~/.pi/agent/models.json` (or `--api-key $OPENROUTER_API_KEY`).
- Vision: `pi -p @contact_sheet.png "…"` — `@file` attaches images. Replaces the Claude vision-message plumbing everywhere in tier C.
- Sessions: `--session <id>`, `-c` continue, `--no-session` ephemeral. Long-lived tmux panes: `tmux new-session -d "pi --session lane-00 …"` — pi is designed for tmux observability; there is no `/clear` — use `--no-session` per dispatch or fresh `--session` names per span (cheaper and simpler than pooled clearing).

### Changes, file by file

1. **`.env`** — add `OPENROUTER_API_KEY`, `PI_BIN` (default `pi`), and per-tier knobs: `MODEL_DEFAULT=qwen/qwen3.5-flash-02-23`, `MODEL_QUALITY=minimax/minimax-m2.5`, `MODEL_VISION=$MODEL_DEFAULT`. Skills read the tier via env, never hardcode.
2. **`_lib/pane.sh`** — the choke point; ~90% of the migration lands here.
   - `run_claude_step` → `run_llm_step <step> <prompt> <reply> [tier]`: no-pane path becomes `pi -p --no-session --model "$model" < prompt > reply`.
   - Pane path (`SHORTS_PANE`): pane bootstraps `pi` instead of `claude`; per-dispatch either send into the interactive pane as today (keep `in.txt`/`out.txt`/`out.done` contract) or — simpler and recommended — drop chat-pane mode and run `pi -p` inside the pane per step (`tmux send-keys "pi -p --model … < in.txt > out.txt && touch out.done"`). Process-pooling motive disappears since pi print-mode startup is light (no subscription session to keep warm).
   - Add a `run_llm_vision_step` that passes `@image` args — removes each skill's bespoke Claude-vision plumbing.
3. **Vision skills (tier C)** — verify-bookends, broll-pick (verify_batch), director-pass, first-span-feedback, profile-clip, grade-clip rubric: swap their Claude vision invocation for `run_llm_vision_step` with `MODEL_VISION`; prompts unchanged, parse_reply fallbacks already guard against weaker models.
4. **`rlm-segment-subcall`** — currently a Claude Task subagent. Replace with direct `pi -p --model "$MODEL_QUALITY" @chunk_NN.txt` calls from the segment-topics orchestrator (bonus: real per-call token usage from `--mode json` replaces the chars/4 proxy in `usage.json`). Delete `.claude/agents/rlm-segment-subcall.md` dependency; keep `RLM_SUBCALL_MODEL` as the override, now an OpenRouter id.
5. **`start.sh` / `shorts.sh`** — pane bootstrap lines (`claude` → `pi`), lane pooling simplification (no `/clear` dance), and any `claude -p` literals.
6. **`autopilot.sh`** — loses the "must be logged into GUI session for subscription auth" constraint entirely (API key auth works headless — a real win: autopilot can run on a locked machine). Update the comment/docs.
7. **First-span-feedback / style-gate fixers** — the "fixer" is an agentic coding session; run it as interactive `pi --session fsf-fix` with a capable model (`MODEL_QUALITY` or better). Their three-gate accept logic is model-agnostic and unchanged.
8. **Docs** — CLAUDE.md "No Anthropic API key" section rewritten: the constraint becomes "OpenRouter key only, tiered models"; mcptube `discover` could now be *allowed* (it needs an LLM key) — decide separately, default keep forbidden.
9. **Crew/ralph** (`~/.claude` layer, out of repo scope) — unaffected for now; flag as follow-up.

### Rollout order

1. `.env` tiers + `pane.sh` `run_llm_step` with a `LLM_BACKEND=claude|pi` switch (default claude) — zero-risk landing.
2. Migrate tier A skills, run one full source with `LLM_BACKEND=pi`, diff grades vs a Claude baseline run (`grade-clip` + `_selection.json` are the oracle).
3. Migrate tier C vision skills; eyeball broll verify accept/reject decisions and director-pass verdicts on the same source.
4. Migrate tier B (pick-segments, RLM) last — it's the quality-determining step; A/B against the Claude baseline before flipping the default.
5. Flip `LLM_BACKEND=pi` default, update autopilot docs, remove the GUI-login requirement note.

### Risks

- **Weaker instruction-following on cheap models** → malformed JSON. Mitigation: every Claude skill already has a deterministic `parse_reply.py` fallback; add one retry-with-error-appended before falling back.
- **Vision quality drop** on broll verify / director-pass → bad cutaway accepts. Mitigation: keep `MODEL_VISION` independently overridable; escalate just that tier if grade distributions shift.
- **OpenRouter provider variance** (same model id, different hosts) → pin `provider.order`/quantization prefs in `~/.pi/agent/models.json` if outputs get flaky.
- **Prompt drift**: prompts were tuned on Claude. Expect one tuning pass per tier (the `FSF_REPLY_FILE`-style test seams make this cheap to iterate).

### Open questions for the operator

- Data routing: cheap tier routes to Chinese-lab-hosted models (Qwen/DeepSeek/GLM via OpenRouter's providers). If unacceptable, defaults become `gemini-2.5-flash-lite` (A/C) + `gpt-5-mini` (B) at ~2-3× cost.
- Keep the pooled-interactive-pane architecture at all, or collapse to `pi -p` per dispatch (recommended)?
- Un-forbid `mcptube discover` now that a key exists?
