# fill-vertical — Spec

> Cold-start handoff contract. A fresh agent with zero conversation context should be able to build the `fill-vertical` skill from this file alone.

## Reference images

- **Target look:** [`reference_shorts/sprite.png`](reference_shorts/sprite.png) — talking heads are chest-up, face ~40–50% of frame height; even B-roll is cropped full-bleed; **zero blur bars anywhere**.
- **Current broken output:** [`reference_shorts/sprite1.png`](reference_shorts/sprite1.png) — every subject shrunk into a blurred letterbox box (two people marooned across a table, slides tiny, huge dead margins). The "webinar" look this spec exists to kill.

## Working definition
A new pipeline skill that reframes a horizontal source clip to 9:16 (1080×1920) by **punching in to fill the frame**, so the human subject reads large on a phone like [`sprite.png`](reference_shorts/sprite.png), instead of being shrunk into a blurred letterbox like [`sprite1.png`](reference_shorts/sprite1.png). It replaces `fit-vertical` in the canonical chain and retires both `fit-vertical` and the orphaned `reframe-vertical`. It is *not* a continuous tracking pan, *not* split-screen, *not* audio diarization, and it produces *no* blur bars.

## Who uses it and how
Invoked per span by `shorts.sh` and `start.sh`, in the slot `fit-vertical` currently occupies — after `tighten-pace`, before `chunk-captions`/`burn-subtitles`. Reads the cut/trimmed/tightened clip, writes a 1080×1920 mp4 with audio stream-copied and duration unchanged. Idempotent via output-vs-input mtime check (same convention as `fit-vertical.sh`).

## Core features
- **Always fill, never letterbox.** Every shot crops to cover the full 1080×1920. No blurred background, no bars.
- **Static crop per shot.** Detect scene cuts (ffmpeg); compute ONE fixed crop box per shot. No motion within a shot → zero in-shot jitter. Crop changes are hard steps aligned to the source cuts.
- **Lip-activity subject pick.** On a multi-face shot, sample a few frames, measure mouth-openness variance per face across the samples, crop to the most active mouth (the speaker). Single-face shots are trivial; ties fall back to biggest/most-central.
- **Tight face framing.** Target the chosen face at ~45% of frame height with the eyeline ~1/3 down (rule-of-thirds headroom), centered horizontally.
- **Saliency crop for no-face shots.** Shots with no detected face crop toward the most salient region (OpenCV saliency / motion energy centroid), not dead center.
- **Upscale cap ~2×.** If hitting the 45% target needs more than ~2× zoom (wide/low-res shot), stop at the cap and frame the face as large as the cap allows — sharper image, slightly smaller subject.

## Rules and edge cases
- **No cuts detected** → whole clip is one shot, one crop box.
- **Zero faces in a shot** → saliency crop (cover zoom only, no artificial upscale beyond fill).
- **Face already larger than 45%** → no zoom, just crop/center; never zoom *out* to add bars.
- **Crop window clamps to source bounds** — never samples outside the frame.
- **Very short shots (<~0.5s)** → still get their own crop from whatever frames sample; if none sampled, center cover. `[guess: rare; not worth special-casing]`
- **Slides / on-screen text** fall through to the saliency path and may get sides chopped — flagged below as a double-check, since saliency was chosen over a slide letterbox exception.
- **CPU budget:** sample only K frames per shot (e.g. ~5), never per-frame detection; reuse `_lib/encode.sh` thread caps. This respects the recent CPU-brick fix (`shorts-xv5`).

## Look and feel
Full-bleed 9:16 on every shot. Talking heads chest-up, face ~45% of height, eyes on the upper third. B-roll cropped to its salient action. The "content" look of [`sprite.png`](reference_shorts/sprite.png), never the "webinar" look of [`sprite1.png`](reference_shorts/sprite1.png).

## Resolved decisions

### Crop motion model
Choice: Static crop per shot (scene-cut detect → one box per shot).
Why: jitter and "just didn't look good" were past failures; a static box removes in-shot motion entirely while per-shot recompute still frames each camera angle correctly. Pure per-clip (one box) was rejected because clips cut between wide masters and solo cams that need different boxes.

### Letterbox policy
Choice: Never letterbox — always crop to fill.
Why: [`sprite.png`](reference_shorts/sprite.png) fills the frame on every shot including B-roll; the user chose "never letterbox — always fill" outright. Accepts that a wide two-person master will crop one person out.

### Subject selection
Choice: Lip-activity (most active mouth across sampled frames).
Why: "locked onto wrong subject" was a past failure and source audio is a single mixed track, so per-speaker audio isn't available locally; lip movement is the local signal for who's actually talking. Biggest-face was rejected as it picks the listener when they're closer to camera.

### Crop tightness
Choice: Face ~45% of frame height, eyeline upper third.
Why: matches the reference's chest-up framing; the user chose tight over medium. Bounded by the upscale cap so it doesn't mush wide shots.

### No-face framing
Choice: Saliency-aware crop.
Why: chosen over center-crop and over a slide-letterbox exception — B-roll gets intentional framing toward the action.

### Upscale cap
Choice: Cap zoom ~2×; accept a smaller face past the cap.
Why: sharpness chosen over subject size when they conflict; tight framing on a wide/low-res master would otherwise hit 3–4× and look soft.

### Codebase shape
Choice: New skill `fill-vertical`; delete `fit-vertical` and `reframe-vertical`; repoint `shorts.sh` + `start.sh`; remove the "use fit-vertical, crop disabled" rule from CLAUDE.md.
Why: clean slate (the user's words); one-atomic-op convention; `reframe-vertical` is already orphaned (no `pick-speaker` producer exists).

## Technical constraints
- **Local, no API.** Detection is MediaPipe **FaceLandmarker** (full lip mesh — required for lip-activity; YuNet's 5 points can't measure mouth openness) `[from gullivan + lip-activity requirement]`. Saliency via OpenCV (`opencv-contrib`, StaticSaliencyFineGrained) or frame-difference motion energy. All crop/scale/concat via ffmpeg. Mac/CPU.
- **Implementation:** `fill_vertical.py` (probe → scene-detect → per-shot sample+detect+score → emit crop boxes) + `fill-vertical.sh` wrapper. Per-shot render = cut→crop→scale-to-1080×1920, then concat-demuxer join; audio stream-copied over the whole clip. `[guess: per-shot segment+concat is more robust than sendcmd, whose crop w/h aren't reliably commandable]`
- **Inputs:** `input`, `out`, optional `target=1080x1920`, and tunables `face_frac=0.45`, `max_zoom=2.0`, `scene_thresh=0.4`, `samples=5`.
- **Output:** 1080×1920 mp4, audio copied, duration preserved, idempotent mtime check, `-movflags +faststart`, encode via `_lib/encode.sh`.
- **Deps to (re)add:** `mediapipe`, `opencv-contrib-python`, `numpy`. Run with `python3`.

## Out of scope
Continuous/tracking pan; split-screen multi-speaker; audio diarization / active-speaker-by-sound; blur bars / letterbox of any kind; slide-specific handling; resurrecting `reframe-vertical` or `pick-speaker`; segment selection, captions, titles, CTA, music (other pipeline skills own those).

## Decisions to double-check
1. **Slides/text graphics** — saliency won't guarantee whole text; if sources have many wide diagrams, the never-letterbox rule will chop them and we may need to revisit the slide exception.
2. **Upscale cap value (2×)** — the exact threshold where "smaller face" beats "soft image" is a taste call; easy to tune after seeing real output, and lip-activity reliability (`[guess: ~70–85%]`) should be eyeballed on a real two-shot.
