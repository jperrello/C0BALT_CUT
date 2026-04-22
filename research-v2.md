# Shorts v2: face-tight + screen-dominant 9:16 layout

Scope: pick ONE concrete layout recipe for 1 VOD → N vertical shorts where
(a) screen content occupies ≥70% of canvas pixels, (b) facecam is always
present as a tight face-only crop, (c) the screen region is dynamically
reframed with L1-smoothed pan so action stays visible. Builds on
`sota-shorts.md`; supersedes `pipeline.py`'s layout choices.

Target source: Tyler1 L34 VOD (`youtube.com/watch?v=8Slai4KZSFo`, 1h34m,
pre-chaptered). Assume 1920×1080 30fps unless `ffprobe` says otherwise.
Tyler1's standard OBS layout anchors the facecam at the bottom-right of
the gameplay frame — our screen reframe must exclude that region from
saliency (we composite a tight face tile separately; the embedded PiP
should not attract the pan).

---

## 1. Critique of v1 (`pipeline.py`)

v1 layout constants:

```
W, H = 1080, 1920
FACE_SIZE = 400      # square face tile
FACE_Y = 40          # face tile at top
GAME_W, GAME_H = 1080, 1400
GAME_Y = 460         # screen panel below face
```

Three structural failures:

**1a. Screen coverage is effectively low, not high.** `1080×1400 /
(1080×1920) = 72.9%` on paper — within spec — but v1 then does
`crop=gw:gh:gx:gy, scale=1080:1400` where `gw = min(sw, sh·(1080/1400)) =
min(1920, 832) = 832`. A 1920×1080 source gets a **832×1080 center
crop**: 57% of source horizontal pixels discarded. The resulting 1080×1400
tile shows a narrow vertical slice of the gameplay scaled up. "Screen
content" is present but cropped so aggressively there is little *action*
in the frame. Effective informative coverage ≈ `72.9% × (832/1920) ≈
31%`. The viewer sees a tall thin pillar of gameplay, not gameplay.

**1b. Face tile is misproportioned AND mis-cropped.** `FACE_SIZE=400` at
the top is 160k px (7.7% of canvas) — small enough to read as
"thumbnail," big enough to draw the eye. Worse, `face_bbox()` does
`pad=0.25` around the detected bbox and then `scale=400:400`. That's not
a tight face crop — that's a loose bbox with hair, shoulders, OBS border
artifacts, and usually a slice of the gameplay behind the PiP all baked
in. The user's "face too dominant" complaint is about perceived
dominance despite the small pixel count: the face sits above, the eye
tracks to it first, and it's visually noisy (loose crop + high
positional weight at the top of the frame).

**1c. No dynamic screen reframe.** `gx = (sw - gw)//2`, `gy = (sh -
gh)//2` — static center crop, no saliency, no pan, no smoothing. If the
action is on the left side of the source (minimap, Tyler1's cursor on
champion select, off-center team-fight), it's outside the 832px center
window and invisible. This fails goal (c) entirely.

**1d. Secondary issues carried forward.**
- `FACE_Y=40` puts the face dead-center top. Face above screen reads as
  a "reaction to a video" layout, not a gameplay layout.
- Face detection uses Haar cascades (`haarcascade_frontalface_default`),
  which misses side profiles and occluded faces common in rage content.
  MediaPipe short-range is strictly better (180+ fps, higher recall on
  profiles). sota-shorts.md already called this out; v1 ignored it.
- Face bbox = median of 8 samples. Median is a stability tactic; it's
  also a jitter-prevention tactic for a problem (per-frame re-detect)
  v1 doesn't have, because v1 doesn't re-detect per frame. The median
  hides the fact that the bbox is never refreshed, so on a clip where
  the streamer moves mid-clip, the crop desyncs.
- Subtitles render via `ass=...` overlay on top of the face-above-screen
  composite. ASS is at `MarginV=220`, which in 1080×1920 is ~200px from
  the bottom — fine for TikTok UI clearance but collides with the
  bottom edge of the 1400-tall screen panel. Fixable but wasn't caught.

Summary: v1 got the canvas dimensions right (1080×1920, H.264 High L4.2,
-14 LUFS) and got everything inside the canvas wrong.

---

## 2. Chosen layout

**Vertical split, screen dominant top, face-tight bottom center, blurred
screen fill on the sides of the face tile.** Pure black bars are the
tell-tale "AI-generated shorts" look; mirroring a dimmed + blurred copy
of the screen under the face tile gives color continuity and hides the
seam without stealing attention.

```
Canvas 1080 × 1920 (9:16, 30fps)

┌─────────────────────────────────────┐  y=0
│                                     │
│                                     │
│         SCREEN  PANEL               │
│     1080 × 1416  (73.75%)           │
│   dynamic saliency+cursor pan       │
│     L1-smoothed trajectory          │
│                                     │
│                                     │
│                                     │
│  ░░░░░░  subtitle band  ░░░░░░      │  ass burn, y≈1180
│                                     │
├─────────────────────────────────────┤  y=1416
│░blur░│   FACE TILE   │░blur░│       │
│ 288  │    504×504    │ 288  │       │  y=1416..1920
│ strip│   MediaPipe    │ strip│       │
│      │  tight crop   │      │       │
└─────────────────────────────────────┘  y=1920
```

Pixel geometry (hardcode these; they're load-bearing):

| Region | Rect (x, y, w, h) | Area | % canvas |
|---|---|---|---|
| Screen panel | (0, 0, 1080, 1416) | 1,529,280 | **73.75%** |
| Face tile | (288, 1416, 504, 504) | 254,016 | 12.25% |
| Blur strip L | (0, 1416, 288, 504) | 145,152 | 7.0% |
| Blur strip R | (792, 1416, 288, 504) | 145,152 | 7.0% |

Target met: **73.75% ≥ 70%** (goal a), face present as its own
dedicated tile (goal b), screen region reframed dynamically (goal c,
detailed in §4).

**Why 1416, not 1440 or 1920 (PiP overlay)?**

- `1920 px screen + PiP face overlay` (OpusClip default): maximizes
  screen coverage but the PiP occludes gameplay. Worse, Tyler1's source
  already has a facecam PiP in the bottom-right of the gameplay — a v2
  PiP of our re-cropped face would double-up. Rejected.
- `1080 × 1440 screen + 1080 × 480 bottom strip` (75%, 25%): splits
  cleanly but 1080×480 wide face is 9:4 — faces are not 9:4, you end
  up scaling a tight face crop to fit a wide tile with black bars on
  the sides of the face *inside* the face tile. Net face size is no
  larger than in our 504-tall design.
- `1080 × 1416 + 504 square tile`: face tile is naturally square (face
  aspect is close to 1:1 after chin-to-hairline framing), bottom strip
  height 1920−1416 = 504 divides cleanly with the face tile width,
  blur strips of 288 each side are wide enough to read as background
  rather than thin letterboxing. 1416 = 1920 − 504 is the constraint;
  1416 is chosen *because* it gives a square 504 face tile.

Subtitles render inside the screen panel with `MarginV` computed against
canvas: `MarginV = 1920 − 1416 + 40 = 544` from bottom → ~236 from the
seam. This places the 2-line subtitle band in the lower third of the
screen panel without colliding with the face tile boundary.

---

## 3. Face crop strategy

**Library**: MediaPipe Face Detection, short-range model
(`model_selection=0`, ~180 fps on M-series). Carries over sota-shorts.md
pick; supersedes v1's Haar cascade.

**Detection cadence**: per-frame detection on the full clip (30–60s at
30fps = 900–1800 frames). MediaPipe at 180fps detects a 60s clip in ~10s
wall time — cheaper than the ffmpeg re-encode pass it feeds. Per-frame is
robust to mid-clip head movement; median-over-samples (v1) is not.

**Smoothing**: One-Euro filter on `(cx, cy, s)` where `s = max(w, h)` of
the bbox. Per MediaPipe issue #3495 / the "Practical Guide to MediaPipe
Smoothing Filters" (Raut, 2024): `min_cutoff = 0.8, beta = 0.007, d_cutoff
= 1.0`. If a frame has no detection (face out-of-frame, obscured by
headset, Tyler1 tilting off-axis during rage), hold the last filtered
value and decay confidence; if > 0.5s without a hit, fall back to the
last high-confidence bbox from the preceding second.

**Tight crop geometry** (the thing v1 got wrong):

```
bbox: (x, y, w, h) from MediaPipe (detects hair-to-chin, ear-to-ear)
pad = 0.12                         # v1 used 0.25; too loose
cx = x + w/2
cy = y + h/2 - 0.06 * h            # shift UP 6% → chin-weighted framing
                                   # (face feels centered, not skull-top heavy)
s = max(w, h) * (1 + pad)          # square crop
crop_rect = (cx - s/2, cy - s/2, s, s)  # clamp to source bounds
```

Scale `crop_rect` → `504×504` with `scale=504:504:flags=lanczos`. No pad
inside the face tile — the crop is already square so no letterboxing is
needed.

**Blur-strip fill**: same source frame → `crop=screen_crop → scale` →
`boxblur=20:2, eq=brightness=-0.15` → placed at `(0, 1416, 288, 504)`
and `(792, 1416, 288, 504)` via `tile`/`hstack` or just two more
`overlay` calls. This is one extra filter-graph branch; ffmpeg doesn't
care. The blur strip is the *screen* signal, not the face — that way
the visual texture at the seam matches the panel above.

---

## 4. Screen reframe strategy

**Pan-and-scan with saliency+cursor fusion, L1-smoothed.** Not static
crop (v1's bug); not per-frame saliency (AutoFlip showed this jitters
without the L1 solve); not full YOLO/SAM (overkill for bbox-level
reframe — sota-shorts.md already ruled out SAM2).

**Source → screen panel mapping.** Source is 1920×1080. Screen panel is
1080×1416. Vertical: panel is taller than source is wide at the matched
AR, so we scale-to-fill width and take a horizontal window:

```
panel_AR_inv = 1080/1416 ≈ 0.763

src crop height = 1080  (use full source height)
src crop width  = round(1080 * 0.763) = 823
scale result    = 823×1080 → 1080×1416 (lanczos)
```

We have a 1097-pixel horizontal pan range (`1920 − 823`). The decision
each frame is: where to center the 823-wide window along x ∈ [0, 1097].

**Per-frame center-x signal:**

```
x_sal(t)  = argmax_x  ∑_{y,x∈window(x,t)} saliency_map(t)    # OpenCV
                                                             # StaticSaliencySpectralResidual
x_curs(t) = cursor position if detected (fast white-pixel-density proxy
            or template match on standard LoL cursor), else None
x_flow(t) = centroid_x of optical-flow magnitude (Farneback dense, 1/4
            resolution, every 3rd frame)

# Fuse:
w_sal  = 0.45
w_curs = 0.40 if x_curs else 0.0
w_flow = 0.15
x_raw(t) = (w_sal·x_sal + w_curs·x_curs + w_flow·x_flow) / (w_sal+w_curs+w_flow)
```

**Saliency masking.** Before computing `x_sal`, zero out the saliency map
in the facecam region of the source (for Tyler1: assume bottom-right
quadrant for the first clip, detect-and-lock thereafter using MediaPipe
on the source frame — same detector we already run for the face tile).
This stops the pan from chasing the embedded PiP (which we're re-
compositing separately).

**L1 trajectory solve.** AutoFlip's core technique. Given raw signal
`x_raw[t]` over T frames, solve:

```
minimize  ∑_t (x[t] - x_raw[t])²              # track the signal
        + λ_1 · ∑_t |x[t+1] - x[t]|            # penalize velocity (L1)
        + λ_2 · ∑_t |x[t+2] - 2·x[t+1] + x[t]| # penalize jerk (L1)
subject to  0 ≤ x[t] ≤ 1097
```

This is a linear program in `T ≤ 1800` variables — trivial for `scipy.
optimize.linprog` with the HiGHS backend; < 200ms per clip. Parameters:
`λ_1 = 8.0`, `λ_2 = 40.0`. Tune on the first rendered clip and lock;
both are in pixel-seconds units and scale-invariant within the
expected range.

The L1 (not L2) penalty is load-bearing: it produces **piecewise-constant
segments connected by sharp pans**, which reads as intentional framing.
L2 produces continuous drift, which reads as motion sickness. This is
the specific design choice AutoFlip's 2020 write-up defends with user
studies.

**Implementation shortcut.** If the full LP solve is too fiddly to land
in one polecat-session, ship v2 with a TV-denoising approximation:
`scipy.signal.medfilt(x_raw, kernel_size=15)` followed by a quantized
step filter to snap to ~40px grid. Visually ≈80% of the L1 solve; no LP
dependency. Flag as `--reframe-mode=tv` vs `--reframe-mode=l1`; ship
`l1` as default if it works, `tv` as proven fallback.

**Static-crop fallback.** If per-frame signal variance is low (gameplay
genuinely doesn't pan, e.g., static menu screens, champ select), the L1
solve naturally produces a near-constant trajectory and we get static
crop for free. No special-case code.

---

## 5. Encoder params

Carry v1 / sota-shorts.md choices unchanged. They're correct.

```
-c:v h264_videotoolbox  (Apple Silicon, hardware-accelerated)
-profile:v high -level 4.2
-b:v 10M  (VBR target, ~8-12 Mbps superset)
-pix_fmt yuv420p
-r 30
-c:a aac -b:a 256k -ar 48000
-af loudnorm=I=-14:LRA=11:TP=-1
-movflags +faststart
```

Two tweaks to consider:

- v1 used `-b:v 8M`; bump to `10M` to stay comfortably inside the 8–12
  Mbps band. Gameplay is high-motion, H.264 at 8M can show macroblock
  artifacts in team-fights. No downside — files stay < 80 MB at 60s.
- v1 audio was `192k`; spec says 256k. Bump it; negligible size impact.

Deliberately **not** changing: the h264_videotoolbox codec (libx264
with `-preset medium` is slower on M-series with no quality win for
this bitrate), the 30fps lock (TikTok/IG don't reward 60fps for
gameplay clips — it's accepted, not amplified), and the -14 LUFS
target (sota-shorts.md §Q6 defended at length).

---

## 6. Risks

**Saliency can be fooled by static UI elements.** In LoL specifically,
the minimap (bottom-right of source) has high-contrast movement even
during idle moments and will grab saliency mass. The facecam-masking
step will also mask the minimap on Tyler1 VODs since both are bottom-
right — acceptable side effect. If gameplay genuinely happens on the
map (global plays), the reframe misses. Accept this as a v2 limitation;
sota-shorts.md Q1 already notes "eval metric for reframe quality" is
an open question — we'll grade the first 5 rendered shorts by hand and
iterate on `(λ_1, λ_2, w_sal, w_curs)` if the pan feels wrong. The
tight face tile below the screen panel is independent of screen-panel
decisions, so reframe failures degrade one region, not the whole
short.

Second-order risks worth naming:
- **MediaPipe miss on rage moments** (head turned fully sideways, eyes
  closed). Hold-last-bbox decay handles it, but if the entire clip
  lacks a good detection (zero hits in 60s), fall back to Haar cascade
  rather than leaving the face tile empty. Empty face tile violates
  goal (b).
- **Tyler1's facecam PiP position isn't locked within a VOD**. If he
  scene-switches mid-stream, our "detect-once-per-clip" facecam-mask
  desyncs and the pan starts chasing the PiP. Re-detect the PiP
  location at clip start (not VOD start) and mask from there.
- **Source resolution not always 1080p.** Test local `source/stream.mp4`
  is 854×480 30fps. Pipeline must detect source dims via `ffprobe` and
  compute `src_crop_w = round(src_h * panel_AR_inv)` proportionally
  rather than hardcoding 823. v1 already does `probe_size`; v2 keeps
  that and wires the result into the reframe math.
- **LP solver is a new dep** (`scipy.optimize` is already in the numpy
  ecosystem, but the HiGHS backend needs `scipy >= 1.9`). Pin it and
  fall back to the TV-denoise path if unavailable so we don't brick
  the pipeline on a fresh install.
- **Blur strips bleed color across the seam.** If the gameplay is very
  bright (fountain, ultimate flash) the blurred version at y≥1416 will
  briefly overpower the face tile. Fix with `eq=brightness=-0.15,
  saturation=0.5` on the blur strip — less saturated, darker, reads as
  background not content.

---

## Handoff to sh-k7n (pipeline_v2.py)

Load-bearing constants for the implementer:

```python
CANVAS = (1080, 1920)
SCREEN_RECT = (0, 0, 1080, 1416)          # 73.75% of canvas
FACE_TILE_RECT = (288, 1416, 504, 504)    # square, bottom-center
BLUR_L_RECT = (0, 1416, 288, 504)
BLUR_R_RECT = (792, 1416, 288, 504)
SUBTITLE_MARGIN_V = 544                    # ASS MarginV, canvas bottom
FACE_PAD = 0.12
FACE_CHIN_SHIFT = 0.06
ONE_EURO = dict(min_cutoff=0.8, beta=0.007, d_cutoff=1.0)
L1_LAMBDAS = (8.0, 40.0)                   # (velocity, jerk)
REFRAME_FUSION = dict(sal=0.45, curs=0.40, flow=0.15)
```

Keep v1's scene detection, audio RMS, Warren-candidate loader, hook
scorer, whisper transcription, and ASS writer — those are orthogonal
to the layout change and sota-shorts.md already defended them. Replace
only `face_bbox()` (→ MediaPipe + one-Euro, per-frame) and `render()`
(→ new filter-graph with screen reframe + tight face + blur strips).
