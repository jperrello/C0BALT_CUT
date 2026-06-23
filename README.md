# 💎 C0BALT_CUT ⚡

Joey here, the creator of C0BALT_CUT. This project is designed to investigate Youtube Short automation. I plan to add customizability in the future along with a free website for you to take this exact idea. In the meantime, if you are not me or named Joey Perrello, please do not use this! It is highly unstable and subject to many changes! Please wait for future news and analytics as C0BALT_CUT continues to grow on YouTube!

### *Zero filler. All payoff.* — the sharpest minute in podcasts. 🔪

> 🎙️ Feed it hours of rambling podcast. 💎 Get back gems.

A **local-first YouTube-shorts factory** that turns long-form video into scroll-stopping 9:16 shorts — fully automated, no API key, running entirely on your Mac. 🖥️🔥

You point it at a podcast, talk, or vlog. It transcribes locally, lets **Claude** hunt down the most clip-worthy story arcs, and surgically edits each one into a tight vertical short: ✂️ filler cut, ⏩ pace tightened, 🎯 punch-in reframe, 🎬 B-roll cutaways, 🅰️ karaoke captions, ✨ cold-open title, 🏷️ branding, 🎵 music. Finished `.mp4`s land under `./output/<source-slug>/<title-slug>.mp4`. 🎉

The channel brand is **[@C0BALT_CUT](brand/BRAND.md)** 💙 — Cobalt = the blue, Cut = the pipeline's atomic unit, and the `0` = **zero filler, zero sag.**

Every single step is an atomic **[Claude Code skill](.claude/skills/)** (`.claude/skills/<name>/SKILL.md`) — independently invocable, idempotent, and chained into one ruthless pipeline. Skills pass JSON on disk between stages, so any stage can be re-run on its own. 🧩

---

## 🛠️ The Stack

- 🗣️ **whisper.cpp** (local, Metal) — word-level transcription from a local GGML model
- 🧠 **Claude** (Claude Code session or `/crew` tmux panes — **NO API KEY**) — *every* semantic decision: topic segmentation, span picking, coherence/bookend/completeness gates, captions, B-roll selection, titles, music mood, and the agentic director pass
- 🎞️ **ffmpeg** — all media ops (cut, crop, loudnorm, overlays, retime)
- 👁️ **MediaPipe / OpenCV** — face detection, identity clustering, saliency cropping
- 🖌️ **PIL** — all text rendering (local ffmpeg has no libass/drawtext, so every overlay is a transparent PNG composited by ffmpeg)

---

## 🚀 Quick Start

```bash
cp .env.example .env   # paths: WHISPER_BIN, WHISPER_MODEL, OUTPUT_DIR
brew install ffmpeg whisper-cpp yt-dlp
pip install mediapipe opencv-python numpy pillow

bash start.sh <youtube-url>        # 🎬 produce shorts from one video
bash start.sh <11-char-yt-id>      # bare YouTube ID
bash start.sh work/<source-id>     # ♻️ reuse an already-ingested source
bash start.sh url1 url2 ...        # 📦 batch, sequential
```

💾 Finished shorts land in `./output/<source-slug>/`; working files in `work/<id>/`. ⚡ Re-runs are **cheap** — every skill skips when its outputs are newer than its inputs.

---

## 🎛️ Entrypoints

| Entrypoint | What it is | When to use |
|---|---|---|
| 🟢 `start.sh` / `/start` | **Primary orchestrator.** Runs the pipeline across long-lived tmux panes (srcprep + analysis + parallel per-span lanes). Resumable — each phase skips when its output exists. | Any full run |
| 🟡 `shorts.sh` | Legacy sequential fallback: same chain, single process. | Debugging one skill, or no tmux |
| 🤖 `autopilot.sh` + `install-autopilot.sh` | **Autonomous cron loop.** A launchd agent fires hourly: 📊 learn from analytics → 🔭 scout sources → 🎯 pick the top unseen candidate → 🏭 produce it → 📥 stage + 🔔 notify. **Stage-and-notify only — never uploads.** | Hands-off daily production |

```bash
bash .claude/skills/scout-sources/scout-sources.sh   # 🔭 rank what to clip NEXT
bash install-autopilot.sh                            # 🤖 arm the hourly loop
bash autopilot.sh --status                           # 📍 loop state
bash autopilot.sh --dry-run                          # 👀 what it would produce next
```

---

## ⚙️ The Pipeline

Each source gets mined through this chain. `scout-sources` (optional, *before* the pipeline) ranks candidate videos by an outlier score — feed the winner to `start.sh`. 🏆

**📥 Source prep:** `ingest` (yt-dlp → source + metadata + most-replayed heatmap) → `transcribe` (whisper.cpp → word-level transcript).

**🎯 Selection:** `segment-topics` (topical chapters; on long sources an RLM map-reduce over seam-cut chunks) → `pick-segments` (Claude picks N clip-worthy spans, each 1-3 assembled cuts, scored on hook/payoff/structure with replay-heatmap + RMS as supporting evidence) → `verify-coherence` → `bookend-trim` (snap to sentence boundaries) → `verify-completeness` (nudge the landing outward if the payoff got cut).

**🎬 Per span — edit → captions/B-roll → finishing:**

```
✂️  cut-clip → trim-filler → cut-filler → tighten-pace → verify-bookends → fill-vertical
🎥  → jump-cut → zoom-punch → chunk-captions → switch-faces
🍿  → broll-pick → broll-composite → fix-cold-open → burn-subtitles → sfx-beats (comedy)
✨  → generate-title → title-transition → brand-overlays → loudnorm
🎵  → like-subscribe-overlay → pick-mood → bg-music → end-card → speed-up
🎬  → director-pass → qc-clip → visual-cadence → name-short → save-local → grade-clip
```

**🏁 Once at end of run:** `broll-cleanup` (evict this run's B-roll cache) → `sources-ledger` (registry of what's been clipped) → `selection-report` (shipped shorts alongside the considered-not-shipped candidates) → `schedule-drip` (stage a daily drip into `output/_toupload/`).

📖 The full canonical definition of every skill, its order, and the hard rules lives in **[`CLAUDE.md`](CLAUDE.md)**.

---

## 💙 Brand Rules Baked Into Every Frame

Every saved short:
- 📐 is **1080×1920 full-bleed punch-in** — never letterboxed, NO blur bars
- ⚡ opens with a **cold-open glitch title** in the top banner over live footage (frame 1 is *content*, never a blocking card)
- 🏷️ shows the source citation in the top banner over the final ~3s
- 👆 carries a like/subscribe CTA within the first third
- 🔁 lands on a **"FOLLOW FOR MORE"** end card

Accent blue everywhere is **Sapphire Glow `#2E6BFF`** 💎; all overlay type is **Impact**. Full kit → **[`brand/BRAND.md`](brand/BRAND.md)**.

---

## 🧹 Disk Hygiene

`work/` balloons to ~**25×** the size of the finished shorts. 😱 `sources-ledger` records what's been clipped (registry + bd memory); `reap-source` is the manual cleanup tool that reclaims heavy artifacts while keeping the lightweight JSON as on-disk memory.

```bash
bash .claude/skills/reap-source/reap-source.sh --backlog --dry-run   # 👀 what a cleanup would free
bash .claude/skills/reap-source/reap-source.sh --backlog             # 🧹 reclaim it
bash .claude/skills/sources-ledger/sources-ledger.sh show            # 📒 the registry
```

---

## 📌 Issue Tracking

This project runs on **bd (beads)** for all task tracking — run `bd prime` for workflow context. 🚫 No ad-hoc TODO files.

## 🗄️ Pre-pivot Archive

The previous Python pipeline (whisperX, mlx-whisper, `pipeline_v2.py`) is preserved on the `archive/pre-pivot` branch.

---

<div align="center">

**💎 C0BALT_CUT — if it didn't earn its seconds, it didn't make the cut. 🔪**

</div>
