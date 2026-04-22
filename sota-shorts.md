# Long VOD → Vertical Shorts: SOTA Survey (2024-2026)

Timebox: report-only. Scope: what off-the-shelf FOSS or published recipe
do we adopt for the six shorts-specific problems, before writing the
MVP pipeline? Peer of `youtube/crew/eddy/sota-research.md`. Picking is
handled upstream (Warren) or by a trivial scene+RMS fallback — this
survey is about the work **between** "here are candidate moments" and
"here is a vertical MP4 TikTok will not throttle."

## Verdict

**Build the MVP with the deterministic stack and escalate only where
rules visibly fail.** The shorts-specific problems are composition,
pacing, and hook framing — not picking. None of them justify SAM2 or a
per-short LLM call in v0.

Layered stack to adopt:

1. **Reframing**: start with `MediaPipe Face Detection + one-Euro
   smoothing` for the facecam region, fixed center-crop with a
   horizontal saliency nudge for gameplay. Upgrade to `YOLOv8n + ByteTrack`
   only when we see a concrete reframing miss on the eval clip. Skip SAM2
   entirely for v0 — its MPS path is unstable and the quality win over
   bbox-crop on gameplay footage is marginal.
2. **Facecam localization**: detect-once-per-segment, not per-frame.
   Facecam position is static within a session for every streamer we'll
   see; OBS scenes don't move the PiP mid-stream. One MediaPipe pass on
   a handful of sampled frames → median bbox → lock.
3. **Subtitles**: `whisperX` for word-aligned timestamps, ASS file with
   `force_style` for v0 (line-level, big, bottom-third). Word-level
   karaoke (per-word ASS `\k` highlights driven by whisperX alignment)
   is the platform-native look — ship it in v1 behind a flag, not v0.
4. **Selection contract**: Warren's `edit-instructions.json` is reusable
   as a candidate source but **not** as a final ranker for shorts.
   Shorts need a re-ranker with `hook_in_first_3s` as a first-class score,
   a 30-60s duration constraint, and a "standalone without preceding
   context" score. Same candidate list, different objective function.
5. **Hook shape**: rules-first.  Interjection-near-RMS-peak
   (`wait`, `no way`, `holy`, `let's go`, `what the`) catches most of
   the high-signal cases at zero inference cost. LLM reserved for the
   "is this hook legible in 3 seconds?" binary check, batched over all
   candidates in one Haiku call.
6. **Platform specs**: single encoder profile is a safe superset —
   1080×1920, 9:16, H.264 High L4.2, CRF 20 / 8-12 Mbps VBR, AAC 48 kHz
   256 kbps. Loudness: target **-14 LUFS integrated, -1 dBTP**.
   Platforms diverge on preference (TikTok/IG reward hotter, YT
   normalizes down) but a single master at -14 LUFS plays everywhere
   without platform-side re-normalization artifacts.

Open gap: no mature FOSS tool takes "1 VOD → N *diverse* shorts"
end-to-end — the commercial tools (OpusClip, Klap, Opus Pro, 2short)
do, but not one of them publicly evaluates on gameplay livestreams.
This is greenfield for a reason: the gameplay domain has different
hook shapes (silent surprise, mechanical highlight) than the
podcast/keynote domain those tools were trained on.

---

## Q1. Reframing: what runs locally, how well?

| Approach | Speed on M-series | Quality on gameplay | Verdict |
|---|---|---|---|
| Static center-crop | realtime (ffmpeg) | loses right-side HUD, minimap, action | v0 fallback only |
| Horizontal saliency nudge (OpenCV `StaticSaliencySpectralResidual` every 1s, clamp pan) | ~400+ fps on 1080p | better than center for most gameplay; jitter without smoothing | **v0 pick for gameplay region** |
| YOLOv8n + ByteTrack subject crop | 47-60 fps with MPS (Ultralytics 2025 bench) | great for FPS/first-person with a clear subject; poor when "subject" is UI | v1 upgrade |
| SAM2 mask-driven crop | ~1-3 fps on MPS; reported MPS runtime errors as of 2025 | best ceiling but we don't need pixel masks — just a center-of-interest | **Skip v0** |
| AutoFlip (Google, MediaPipe) | CPU, realtime | purpose-built for this; Google dropped support March 2023 | Reference recipe only |

Two findings that shape the decision:

**AutoFlip is the published recipe we should copy even though the
project is dead.** Google's 2020 write-up is still the clearest public
description of the saliency-guided reframe pipeline: per-frame saliency
+ face/object detection → signal fusion → solve for a camera path
(static / panning / tracking) using an L1-penalty trajectory that
minimizes movement. The code exists in the MediaPipe repo but Google
ended support 2023-03-01. Fork-and-strip is higher effort than
rebuilding the 3-stage recipe ourselves on top of OpenCV + MediaPipe
primitives that *are* maintained.

**YOLOv8 + MPS is the realistic performance ceiling.** Published
benches put YOLOv8n at 47-60 fps on Apple Silicon with MPS enabled
(~16-21 ms/frame), and MediaPipe Face Detection hits 180-200 fps on
comparable hardware. Either is faster than realtime on 1080p 30 fps
source. We won't be CPU-bound on detection; we'll be I/O-bound on
re-encoding. This means we can afford per-frame detection in v1 without
needing to mint a parallelization helper polecat — the reframe pass is
cheaper than the ffmpeg encode pass it drives.

**SAM2 on Apple Silicon is not production-ready in 2025-2026.** The
upstream repo has open issues for MPS crashes on realistic video
lengths, and the model is 2-3 orders of magnitude slower than YOLOv8
for the same bounding-box outcome we actually need. There's no quality
case for it on gameplay: segmenting "player + gun + crosshair" to the
pixel doesn't help the crop; a loose bbox is sufficient.

Techniques to adopt:

1. **L1-trajectory smoothing for the crop center.** AutoFlip's core
   insight: raw per-frame saliency produces jitter; solving for a
   piecewise-constant or gently-panning trajectory with an L1 penalty
   on motion produces watchable reframes. Implementable as a 1-D
   post-process on the per-frame center-x signal.
2. **One-Euro filter on the facecam bbox.** Standard practice (see
   MediaPipe jitter issues #825, #3495). `min_cutoff=1.0, beta=0.007`
   is the common starting point.
3. **Detect-once-then-lock for static regions.** For single-source
   gameplay VODs, the facecam doesn't move mid-stream. Don't re-detect
   per frame.

## Q2. Facecam localization

The actual engineering question isn't "can MediaPipe find a face" —
yes, trivially, at 180+ fps — it's "does the facecam move often enough
to justify per-frame tracking." Empirically: no.

- OBS scene layouts are static within a session. The facecam PiP moves
  only when the streamer changes scene (starting/ending stream, brb).
- Across sessions: yes, streamers do reposition (different games, new
  overlay packs). But that's a session-boundary change, not a mid-clip
  one.

Recipe for v0:

1. Sample 10 evenly-spaced frames from the chosen 60s clip window.
2. Run MediaPipe Face Detection (short-range model, `model_selection=0`)
   on each.
3. Take the median bbox. Expand by ~15% padding.
4. Use that bbox for the whole clip. No per-frame tracking.

If median bbox variance exceeds a threshold (facecam moves within
clip), fall back to per-frame detect + one-Euro smoothing. This
fallback case should be rare.

Edge case: some VODs have the facecam composited *into* the gameplay
region (handheld phone overlay, reaction-cam style). Our crop region
for gameplay will then overlap the face region. This is a v1 problem —
detect overlap and either (a) inpaint the face region out of the
gameplay crop (heavy) or (b) present the face region directly as the
PiP and mask it out of the gameplay tile (lighter).

## Q3. Subtitle styling: line vs. word-level karaoke

**Ship line-level ASS in v0. Add word-level highlights in v1 behind a
layout flag.** Both paths share the same whisperX output so the cost of
upgrading is layout, not transcription.

### Line-level ASS via `force_style` (v0)

whisperX gives us word-accurate timestamps; group into 3-6 word lines
with max 2 lines visible, snap line breaks to phrase boundaries
(comma / period / silence > 200 ms). Render as SRT, burn with
`ffmpeg -vf "subtitles=x.srt:force_style='FontName=Inter,FontSize=72,
PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=3,BorderStyle=1,
Alignment=2,MarginV=200'"`.

Known-good style for TikTok: large (60-80pt on 1080p), bold sans-serif
(Inter / SF Pro / Montserrat), white with black outline, bottom-third
positioned but above TikTok's own UI (~180-240px margin from bottom).

### Word-level karaoke (v1)

Two implementation paths:

1. **ASS `\k` karaoke tags** — whisperX word alignment → generate ASS
   with per-word `\k<centiseconds>` tags, which ffmpeg's libass
   renderer supports natively. No custom renderer needed. NyuFX and
   similar tools generate ASS with karaoke effects; we generate the
   ASS file directly from whisperX output (each word → one `\k` span).
2. **`--highlight_words True` (whisperX built-in)** — emits SRT with
   the current word bolded/colored per time slice. Simpler, less
   customizable. Known pattern: one visible word at a time with a
   color pulse on the active word. Validated recipe documented in
   medium/dl4senses and in the whisperX-subtitles-replicate repo.

Either path is ~1 day of work on top of whisperX being wired up. The
reason to defer: v0 should prove the end-to-end pipeline with a
layout that can't be faulted for stylistic reasons. Line-level
captions are universally legible; word-level karaoke has opinions
(font choice, highlight color, pop animation) that should be tuned
against a real output, not guessed.

### ASR choice

`mlx-whisper large-v3` for transcription + `whisperX` just for its
phoneme-forced-alignment pass to get word timestamps. (whisperX's
transcribe step is faster-whisper-backed and doesn't benefit from
MLX; the alignment pass is CPU-bound on wav2vec2 and cheap.) On a
60s clip this is a few seconds end-to-end. Don't run whisperX on the
full VOD; run it per-clip after trimming.

## Q4. Can Warren's `edit-instructions.json` drive shorts directly?

**Candidate list: yes. Final ranking: no.** Same semantic problem
(find interesting moments), different objective function
(self-contained + hook-in-3s + 30-60s, not 3-6min narrative arc).

Warren's contract is a ranked list of spans with `standalone_score`,
`start`, `end`, `why`. For shorts we:

- Use the candidate set as-is (union with our scene+RMS fallback if
  Warren hasn't run on this source).
- Apply a shorts-specific re-ranker that computes:
  - `hook_present`: does the first 3 seconds of the span contain an
    interjection, question, or visible action onset? (See Q5.)
  - `duration_fit`: penalize spans > 120s or < 10s; prefer 20-45s
    core action ± 5-10s lead/tail.
  - `standalone_3s`: re-prompt the existing standalone-score criterion
    but asking "if a viewer started watching at second 3 of this span,
    would they be confused?"
  - `variety`: min-gap constraint across selected shorts; don't ship
    5 shorts from the same 10-minute window.
- Trim: within each candidate, find the tightest 30-60s window that
  places the payoff between t=3s and t=15s.

This is Moment-GPT's generate-then-rank split, adapted: Warren
generates, we re-rank for the shorts objective. No need to re-run the
expensive transcript pass; we only need the spans and their transcript
snippets.

If Warren hasn't run on a source, the fallback is the same pipeline
Eddy uses: `PySceneDetect AdaptiveDetector` + `librosa RMS
z-score > 1.5` + optional interjection-keyword filter. This is enough
for an MVP without requiring Warren as a dependency.

## Q5. Hook-shape detection

The structural claim from commercial tools (OpusClip / Klap / Opus
Pro) is that effective shorts follow a small set of shapes: **setup →
reaction**, **question → beat → answer**, **cold open of the payoff
with context revealed second**. Converged research and platform data:
videos retaining 65%+ of viewers past 3 seconds get 4-7x the
impressions of those that don't (JoinBrands, Brandefy, OpusClip
blog). The first 3 seconds is the entire game.

**v0 rule-based detector (zero inference cost):**

```
interjection_set = {"wait", "wait wait", "no way", "no no no",
                    "oh my", "oh god", "holy", "let's go", "what the",
                    "are you kidding", "bro", "dude"}

for each candidate span:
  transcript_head = words in [start, start+3s]
  transcript_peak_window = words around (RMS argmax in span)
  hook_score = (
    + 1.0 * (transcript_head ∩ interjection_set non-empty)
    + 0.5 * (transcript_head ends with "?")
    + 1.0 * (RMS z-score at t < 3s > 1.5)  # audible reaction early
    + 0.5 * (scene cut at t in [0, 1s])    # visual hook
  )
```

This is diagnostic, not prescriptive. It won't *create* hooks, but it
will demote spans whose setup is boring and whose payoff is at the
back. Combined with the trimmer (Q4), it pushes the window selection
toward placing the hook early.

**v1: LLM binary check over candidates.** Single Haiku call with all
candidate transcript snippets, asking per-span: "Does the first 3
seconds of this transcript work as a standalone hook for a TikTok
viewer with no context? Y/N with one-sentence reason." Batched, ~1c
per run. Don't call Sonnet for this.

**Do not** try to have the LLM *generate* a hook overlay in v0.
That's the "OpusClip viral-score" problem, which is fundamentally
"predict engagement on platform data we don't have." Our proxies are
cheaper and defensible. Revisit when we have ground-truth retention
data from our own uploads.

## Q6. Platform specs — what do TikTok / Shorts / Reels actually want?

Current public guidance (April 2026):

| Spec | TikTok | YT Shorts | IG Reels | Safe superset |
|---|---|---|---|---|
| Aspect | 9:16 | 9:16 | 9:16 | 9:16 |
| Resolution | 1080×1920 | 1080×1920 | 1080×1920 | **1080×1920** |
| Framerate | 30 (60 accepted) | 30 or 60 | 30 | **30** |
| Duration | up to 10 min (180s sweet spot) | up to 3 min | up to 3 min | **30-60s** |
| Video codec | H.264 High L4.2 | H.264 (AV1 accepted) | H.264 | **H.264 High L4.2** |
| Video bitrate | 8-15 Mbps VBR | ≥ 8 Mbps, 8-12 Mbps VBR | 5-10 Mbps (IG re-encodes to ~3.5) | **8-12 Mbps VBR / CRF 20** |
| Audio codec | AAC-LC | AAC | AAC | **AAC-LC** |
| Audio rate | 44.1 or 48 kHz | 48 kHz, 320 kbps recommended | 48 kHz, 256 kbps | **48 kHz, 256 kbps** |
| Integrated LUFS | -10 to -12 preferred (hotter) | -14 (normalized down above) | hotter rewarded, not normalized as aggressively | **-14 LUFS** |
| True peak | -1 dBTP | -1 dBTP | -1 dBTP | **-1 dBTP** |
| File size cap | < 150 MB (mobile upload), much higher via desktop | 256 GB (effectively unlimited) | ~650 MB (Reels) | **< 150 MB** |

**Single-master strategy.** Encode once at 1080×1920, H.264 High L4.2,
CRF 20 (falls inside the 8-12 Mbps target for typical gameplay
complexity), AAC 48 kHz 256 kbps, normalized to **-14 LUFS integrated
/ -1 dBTP**. This satisfies all three platforms without per-platform
variants.

**The LUFS debate is real but small.** TikTok and Instagram reward
louder masters (some guidance suggests -10 to -12 LUFS) because
mobile-first listening on speakers is quieter than intended. YouTube
normalizes anything above -14 *down*. If we master at -10, YT turns it
down by ~4dB and IG/TikTok leave it alone; if we master at -14, YT
leaves it and TikTok plays quieter-but-not-wrong. **Master at -14** —
it's the standard the mastering chains already know how to hit, and
being 4dB quieter on TikTok is a smaller problem than being 4dB louder
on YT where normalization can introduce perceptible gain-riding
artifacts. Revisit if retention data shows the hotter master wins.

Normalization toolchain: `ffmpeg -af "loudnorm=I=-14:LRA=11:TP=-1"`
(EBU R128 two-pass for accuracy). Single-pass is fine for v0; upgrade
to two-pass if we hear pumping.

Encode command skeleton (v0):

```
ffmpeg -i input.mp4 \
  -c:v libx264 -profile:v high -level 4.2 -preset medium -crf 20 \
  -pix_fmt yuv420p \
  -r 30 -vf "scale=1080:1920:force_original_aspect_ratio=decrease,
            pad=1080:1920:(ow-iw)/2:(oh-ih)/2" \
  -c:a aac -b:a 256k -ar 48000 \
  -af "loudnorm=I=-14:LRA=11:TP=-1" \
  -movflags +faststart \
  output.mp4
```

---

## Open questions for future spikes

1. **Hot-master A/B** (master-at-14 vs master-at-10) — needs our own
   upload + retention data from all three platforms.
2. **Facecam overlap case** — what fraction of VODs have the facecam
   composited into the gameplay region rather than as a separate PiP?
   Inspect the test stream before designing v1.
3. **Gameplay-specific hook shapes** — silent-reaction highlights (no
   verbal cue at all) are common in competitive gameplay and our
   transcript-based rules will miss them. Complements the
   optical-flow-during-ASR-silence gap flagged in `youtube/crew/eddy/
   sota-research.md`. Same open question, both rigs.
4. **Duration sweet spot** — public TikTok guidance is trending longer
   (30-60s no longer the universal floor; longer-form TikTok is
   rising). Is a 60-90s variant worth generating alongside 30-45s?
   Platform-signal question, not a pipeline one.
5. **Eval metric for reframe quality** — we have no automated way to
   grade "did the reframe lose the action." Human A/B is the
   reasonable v0 eval. Later: compare reframed-crop saliency mass to
   full-frame saliency mass as a proxy.

## Sources

- [YouTube Shorts specs 2026 (vidIQ)](https://vidiq.com/blog/post/youtube-shorts-vertical-video/)
- [YouTube recommended upload encoding settings](https://support.google.com/youtube/answer/1722171)
- [TikTok upload technical guide 2026 (InfluenceFlow)](https://influenceflow.io/resources/tiktok-and-instagram-reels-requirement-template-complete-technical-creative-guide-for-2026/)
- [TikTok audio mastering guide (Genesis Mix Lab)](https://genesismixlab.com/ai-mastering/mastering-for-tiktok/)
- [Best loudness normalizers for social video (OpusClip)](https://www.opus.pro/blog/best-loudness-normalizers)
- [Instagram Reels export settings 2026](https://www.stayabundant.com/blog/best-instagram-reels-export-settings)
- [WhisperX (m-bain)](https://github.com/m-bain/whisperX)
- [WhisperX word-level timestamp tutorial (GoTranscript)](https://gotranscript.com/public/master-word-level-timestamping-with-whisperx-a-comprehensive-tutorial)
- [whisperx-subtitles-replicate (word-level SRT recipe)](https://github.com/dashed/whisperx-subtitles-replicate)
- [Single-word subtitles — ASS karaoke approach](https://medium.com/@didierlacroix/the-power-of-single-word-subtitles-662f8c3891bd)
- [FFmpeg subtitles filter + force_style (Bannerbear)](https://www.bannerbear.com/blog/how-to-add-subtitles-to-a-video-with-ffmpeg-5-different-styles/)
- [NyuFX (ASS karaoke authoring)](https://github.com/Youka/NyuFX)
- [Google AutoFlip blog (2020)](https://opensource.googleblog.com/2020/02/autoflip-open-source-framework-for.html)
- [AutoFlip docs — MediaPipe legacy (support ended 2023-03-01)](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/autoflip.md)
- [Katna (FOSS saliency-aware video crop)](https://github.com/keplerlab/katna)
- [Adobe Premiere Auto Reframe docs](https://helpx.adobe.com/premiere-pro/using/auto-reframe.html)
- [YOLOv8 MPS benchmarks on Apple Silicon](https://tech.aru-zakki.com/en/m2-mac-gpu-benchmark-with-yolov8/)
- [YOLO vs MediaPipe face detection comparison (Sieve)](https://www.sievedata.com/resources/how-to-run-face-detection-with-yolo-and-mediapipe)
- [MediaPipe smoothing / jitter guidance (One-Euro)](https://github.com/google/mediapipe/issues/3495)
- [MediaPipe pose smoothing filters practical guide](https://medium.com/@debasishraut-dev/setting-up-smoothing-filters-for-mediapipe-pose-estimation-pipeline-a-practical-guide-fcc03f462196)
- [SAM2 MPS issue tracker (runtime errors on Apple Silicon)](https://github.com/facebookresearch/sam2/issues/687)
- [OpusClip TikTok hook formulas blog](https://www.opus.pro/blog/tiktok-hook-formulas)
- [3-second rule (Teleprompter / JoinBrands)](https://www.teleprompter.com/blog/tiktok-3-second-rule)
- [Psychology of viral video openers (Brandefy)](https://brandefy.com/psychology-of-viral-video-openers/)
