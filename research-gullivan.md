# Gullivan research — long→short pipelines + selective subtitles

Sourced via gullivan-shorts (crew, instance=shorts) on 2026-05-05. Tavily-primary; SerpAPI Scholar unavailable. No synthesis — ranked sources + one-line takeaways.

## PART 1 — This codebase

### What it does
1 long gameplay VOD → N vertical 9:16 shorts (30–60s), face-tight + screen-dominant layout, burned subtitles, ready for TikTok/Shorts/Reels (`shorts-plan.md:8-13`, `sota-shorts.md:1-9`).

### Pipeline state — handles vs TODO

**Already in `pipeline_v2.py`:**
- Candidate generation: PySceneDetect AdaptiveDetector + librosa-style RMS z-score scoring (`detect_scenes`, `audio_rms`, `score_scenes`); Warren `edit-instructions.json` loader exists in v1 but not wired into v2 main.
- Window shaping around RMS payoff with 30–60s clamp + 1s lead (`shape_window`).
- Per-frame face detection via OpenCV YuNet (overrides `research-v2`'s MediaPipe pick — see comment at `pipeline_v2.py:97-99`), facecam constrained to bottom-half of frame, One-Euro smoothing on (cx, cy, s) (`detect_faces`, `one_euro`, `smooth_face`).
- Screen reframe: spectral-residual saliency + Farneback optical flow fusion (saliency masked at face region), L1 LP-solve via scipy/HiGHS with TV-denoise fallback (`compute_reframe_signal`, `smooth_reframe_l1`, `smooth_reframe_tv`).
- Compositor: 1080×1416 screen panel + 504² face tile + dimmed/blurred screen fill on the bottom strip (no pure black bars) (`compose_frames`).
- Subtitle ASR via mlx-whisper large-v3, line-level ASS at MarginV=544, libass burn (`transcribe`, `write_ass`).
- Encode: h264_videotoolbox High@L4.2, 10M VBR, AAC 256k 48kHz, loudnorm I=-14 LRA=11 TP=-1, faststart.
- Delivery contract: copies result to `/Users/jperr/Documents/shorts/delivered/<bead>-<ts>-<stem>.mp4` (`deliver`, `README.md:1-31`).

**Still TODO / open:**
- Hook scorer (`hook_score`, `HOOK_WORDS` interjection set) exists in v1 only — v2 main doesn't use it; ranking is just `score_scenes` energy×log(density).
- Word-level karaoke subtitles deferred to v1+ behind a flag (`sota-shorts.md:142-181`); v2 still ships line-level only.
- Cursor channel of reframe fusion explicitly omitted (`pipeline_v2.py:226` "Cursor channel omitted for v2.0").
- LLM-binary "is hook legible in 3s" check (planned Haiku batch call) not implemented (`sota-shorts.md:262-269`).
- Variety / min-gap re-ranker, `hook_in_first_3s`, `standalone_3s`, `duration_fit` re-ranking (`sota-shorts.md:200-213`) not in v2 main.
- Auto-generated hook overlays, LLM titles/hashtags, multi-variant A/B (`shorts-plan.md:80-86`).
- Eval/QC for reframe quality is hand-grading only (`sota-shorts.md:344-345`, `research-v2.md:312-318`).
- Facecam-overlap edge case (PiP composited into gameplay) and global-play minimap reframe miss are accepted v2 limitations (`research-v2.md:307-318`).

### Prior research notes we can lean on
- **Highlight selection / hook detection:** rule-based interjection-near-RMS-peak detector with weighted hook score; LLM binary check planned as v1 — `sota-shorts.md:227-269`. Generate-then-rank split: Warren generates spans, shorts re-ranks on shorts-specific objective — `sota-shorts.md:192-214`. v0 hook-shape claim (3s rule, 65%+ retention → 4-7× impressions) cited from OpusClip blog / JoinBrands / Brandefy.
- **Subtitle styling:** line-level ASS via `force_style` for v0 (Inter/SF Pro/Montserrat, 60-80pt, white+black outline, MarginV~200-240px); word-level karaoke via either ASS `\k` tags from whisperX alignment or `whisperX --highlight_words True` — `sota-shorts.md:142-181`. v2 actually ships Helvetica 72pt, MarginV=544 to clear face tile seam.
- **Reframe:** AutoFlip's L1-trajectory smoothing recipe (piecewise-constant pans, not L2 drift) defended at `research-v2.md:241-261`; saliency+cursor+optical-flow fusion weights (0.45, 0.40, 0.15) at `research-v2.md:218-232`; λ_1=8.0, λ_2=40.0.
- **Face crop:** tight pad=0.12 (not 0.25), chin-shift -0.06h, One-Euro (min_cutoff=0.8, beta=0.007, d_cutoff=1.0) — `research-v2.md:171-179, 360-363`. v2 swapped MediaPipe → YuNet citing better small-PiP recall.
- **Encoder/loudness:** -14 LUFS / -1 dBTP single-master defended at `sota-shorts.md:271-307`.

## PART 2 — Online alternatives (2025/2026)

### Open-source pipelines (long → vertical shorts)

1. **SamurAIGPT/AI-Youtube-Shorts-Generator** — https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator
   Self-described OpusClip alt; LLM highlight detection + Whisper + auto vertical crop, no watermarks.
2. **Anil-matcha/ai-clipping-comfyui** — https://github.com/topics/vertical-video?o=asc&s=stars
   ComfyUI nodes: server-side Whisper, virality ranking, dedupe, face-tracked auto-crop via muapi.ai. Closest match to a self-hostable Opus Clip.
3. **alperensumeroglu/ai-clips-maker** — https://github.com/alperensumeroglu/ai-clips-maker
   Modular Python: transcription + speaker diarization + scene detection + 9:16 reframe. MIT.
4. **imgly/videoclipper** — https://github.com/imgly/videoclipper
   Browser-only (CE.SDK WASM): ElevenLabs/Whisper word transcript → Gemini picks clips → face-api.js speaker tracking. Architecture is a clean reference for "transcript → LLM picks spans → frame-accurate trim."
5. **ArkounM/YT_to_Shorts** — https://github.com/ArkounM/YT_to_Shorts
6. **Aseiel/VideoHighlighter** — https://github.com/Aseiel/VideoHighlighter
   Fuses scene detect + motion + audio peaks + YOLO object detect + action recognition + transcript keyword scoring. Closest signal mix to our gameplay use case.
7. **artryazanov/shorts-maker** — https://github.com/topics/vertical-video?o=asc&s=stars
   Specifically targets gameplay footage; combines audio + video action profiles to rank scene intensity. Direct peer of our pipeline.
8. **KazKozDev/auto-vertical-reframe** — https://github.com/topics/vertical-video?o=asc&s=stars
   Scene-aware 9:16 auto-reframe CLI (subject-preserving). Reframe-only, useful as a drop-in for our reframe stage.
9. **line/lighthouse** — https://github.com/line/lighthouse
   EMNLP 2024 / ICASSP 2025-26 lib for Moment Retrieval + Highlight Detection (MomentDETR, QVHighlights). Caveat: 150s max video, GPU recommended. The closest research-grade highlight detector with reusable checkpoints.

### Commercial tools — what they actually do
10. **Klap vs Opus Clip** (Red11Media, 2025) — https://www.red11media.com/blog/klap-vs-opus-clip
    Opus Clip = "Virality Score" ranking + speed; Klap = output quality, 4K, brand templates, 29-language dub. Same hook-finding pipeline class.
11. **OpusClip alternatives roundup** — https://exemplary.ai/blog/top-opus-pro-alternatives
    Submagic = caption polish only (no clip-picking AI); 2short = face-tracked center; Vizard "Spark 1.0" claims keyword-guided highlight selection ~50% cheaper than OpusClip.
12. **Submagic vs OpusClip** (Wavel) — https://wavel.ai/compare/submagic-vs-opusclip
    Confirms Submagic's lane is animated/stylized captions, OpusClip's is highlight detection + virality score. The two are complements, not competitors.
13. **Drone&Cam OpusClip alternatives 2025** — https://droneandcam.com/en/post/opus-clip-alternatives-which-tool-to-choose-in-2025/
    Common complaint: OpusClip picks moments "somewhat randomly," subtitle customization is shallow; Vizard wins on context awareness.
14. **OpusClip's own clipping-tools post** — https://www.opus.pro/blog/clip-videos-quickly
    Self-description of the pipeline: complete-thought segmentation, confidence-scored suggestion categories (highlight / hook / educational / CTA), 30-min video < 2 min processing.

### Subtitle strategies (selective / per-word / karaoke burn-in)
15. **Fliki — Burned-in subtitles 2025** — https://fliki.ai/blog/burned-in-subtitles
    Distinguishes karaoke (sync-highlight), phrase, and word subtitles; per-word is the TikTok-native style for 2025.
16. **SubtitlesFast karaoke captions** — https://subtitlesfast.com/tiktok-karaoke-captions
    Productized word-level karaoke burn pipeline; confirms market expectation that "karaoke captions" = word-by-word color/scale highlight, not full transcript.
17. **Taption — 2025 short-video subtitle design tips** — https://www.taption.com/blog/en/2025-short-video-subtitle-design-tips-en
    5 design rules for 2026 short-form captions (Oct 2025 publish). Useful as a style spec source.
18. **Swiftia — best ways to add subtitles 2025** — https://swiftia.io/best-ways-to-add-subtitles-to-short-videos-tiktok-reels-shorts-in-2024/
    Survey of caption tools and the platform-by-platform engagement case for burn-in.

### Multimodal / academic angle (highlight detection on livestreams)
19. **Multi-Modal Livestream Highlight Detection** (PhD thesis, White Rose) — https://etheses.whiterose.ac.uk/id/eprint/32406/1/PhD_Thesis__Revised_.pdf
    Ringer's thesis: AutoHighlight (LoL esports), AAAI '20 chat-driven highlights. Most directly relevant academic source for gameplay-livestream highlights — exactly our domain.
20. **LiveCC / LiveStar / VideoLLM-online** (NeurIPS 2025 + arXiv) — https://showlab.github.io/videollm-online/ , https://neurips.cc/virtual/2025/poster/119920
    Streaming Video-LLMs that emit text aligned to video stream tokens; promising for "describe the hook" but they target real-time commentary, not offline clip ranking.
21. **LiViBench** (arXiv 2601.15016) — https://arxiv.org/html/2601.15016v1
    First omnimodal benchmark for interactive livestreams including audio + speech + chat. Reference for evaluation if we ever want to measure highlight quality formally.
22. **Real-Time Game Commentary with MLLMs** (arXiv 2603.02655) — https://arxiv.org/html/2603.02655v1
    Pause-aware decoding for game video → commentary. Adjacent: shows MLLMs can track gameplay events without fine-tuning, which validates "Haiku binary hook check" as plausible.
23. **Integrating Temporal Event Prediction + LLMs for game commentary** (MDPI Mathematics 2025) — https://www.mdpi.com/2227-7390/13/17/2738
    Surveys template + LLM hybrid approaches for esports commentary; documents the "post-hoc generation lag" problem that also bites highlight detectors.

## Contested / unclear

- Whether the commercial "virality score" actually works. OpusClip markets it as load-bearing; Vizard and reviewers (Drone&Cam, exemplary.ai) say OpusClip's selections feel random and Vizard's context-aware Spark 1.0 is better. No public eval on either claim, especially on gameplay.
- Per-word vs phrase captions. Fliki and SubtitlesFast push word-level as the 2025 default; Taption / Swiftia treat it as one style among several. **"Selective burn-in only on engaging moments" (the user's specific ask) is not a documented commercial pattern** — every tool surveyed burns in the full transcript and uses per-word emphasis (color/scale/emoji on hot phrases) to differentiate peaks. That is the available proxy for what the user wants.

## Couldn't find

- A FOSS or commercial tool that selectively suppresses subtitles outside hot moments (transcript-burn only on engaging spans, blank elsewhere). Closest analogue is whisperX's `--highlight_words` which still shows the surrounding line.
- A published benchmark for gameplay-livestream highlight detection at the SOTA-paper level — Ringer's thesis and the AutoHighlight LoL paper are the best on offer, both 2020-2022 vintage. No 2025 peer-reviewed paper found that benchmarks gameplay-VOD-to-shorts.
- SerpAPI Scholar was unavailable (`$SERPAPI_KEY` unset); academic results above came from Tavily and may miss canonical citations.
