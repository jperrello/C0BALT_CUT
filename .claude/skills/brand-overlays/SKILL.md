---
name: brand-overlays
description: Composite both persistent brand PNGs — the top "Original video: <title>" credit chyron (y≈4%) and the bottom @C0BALT_CUT watermark (y≈97.5%) — onto a finished short in ONE ffmpeg pass. The credit appears only in the FINAL CREDIT_TAIL seconds (default 3.0s) — it fades in at dur-tail and holds to the end so it lands on the closing beat, leaving the cold-open title to own the top banner uncontested at the open; the watermark holds the whole clip. Replaces the back-to-back source-credit + watermark re-encodes in the orchestrator (saves a full re-encode and an intermediate .mp4 per span); those two skills remain the standalone single-overlay ops and own the PNG renderers this skill reuses.
---

# brand-overlays

```bash
.claude/skills/brand-overlays/brand-overlays.sh <input.mp4> <ingest.json> <out.mp4>
```

One ffmpeg invocation, two `overlay` filters chained:

- `../source-credit/render_credit.py` renders the "Original video: <title>" banner (title read from `ingest.json`), composited top-center at `y='H*0.04'`.
- `../watermark/render_watermark.py` renders the @C0BALT_CUT mark (Platinum `#E8ECF1`, slashed-zero in Sapphire Glow `#2E6BFF`), composited bottom-anchored at `y='H*0.975-h'`.

Pixel-identical placement to running `source-credit` then `watermark` sequentially. Audio is stream-copied; video encoded once via `_lib/encode.sh` (`vt_args mid`).

Idempotent: skips when `<out>` is newer than `<input>` and `<out>.bometa` matches the title signature.

In the canonical chain it runs AFTER title-transition and BEFORE loudnorm, producing `clip_NN.marked.mp4` directly from `clip_NN.titled.mp4`. If it fails, the orchestrator falls back to the two-pass source-credit → watermark path.
