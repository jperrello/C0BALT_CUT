# C0BALT CUT — Brand Kit

Handle: **@C0BALT_CUT** · Wordmark: **C0BALT CUT** (the `0` is always the slashed-zero / gem-cut play button, never a plain O)

## Identity

- **Name logic:** Cobalt = the blue. Cut = the pipeline's atomic unit (`cuts` array — 1-3 precision slices assembled into one story). The `0` = zero filler, zero sag.
- **Tagline:** *Zero filler. All payoff.*
- **Alt tagline:** *The sharpest minute in podcasts.*
- **Voice:** a jeweler, not a butcher. Confident, precise, no hype-bro language. Every caption and title earns its seconds.

## Palette

| Role | Name | Hex |
|---|---|---|
| Primary | Cobalt | `#0047AB` |
| Accent / glow | Sapphire Glow | `#2E6BFF` |
| Background | Carbon Black | `#101418` |
| Text / highlights | Platinum | `#E8ECF1` |

Rules: Carbon Black is always the canvas. Cobalt is the brand, Sapphire is light hitting it. Platinum only for type. No other hues anywhere in channel art.

## Type

Heavy geometric sans for the wordmark (Archivo Black / Space Grotesk Bold). All-caps, wide tracking: `C 0 B A L T  C U T`.

## Logo mark

A faceted cobalt gemstone cut into a play-button triangle — point facing right — rim-lit with sapphire glow on carbon black. The same facet geometry appears in the `0` of the wordmark.

## Channel description (YouTube About)

> The sharpest minute in podcasts.
>
> We mine hours of conversation and keep only the cuts — the story that stops you, the line that rewires you, the joke you'll send to three people. Every clip is sliced hook→payoff with the sag removed: no rambling intros, no dead air, no filler. Zero. That's the 0.
>
> Interesting · Motivational · Funny · Life-changing — if it didn't earn its seconds, it didn't make the cut.
>
> New cuts daily. Original creators always credited on screen.

(Short version for places with tight limits: *"Podcast moments cut like gems — zero filler, all payoff. Original creators always credited."*)

## Image-gen prompt — profile picture (1:1)

> A minimal vector logo on a near-black background (#101418): a single faceted gemstone shaped like a play-button triangle pointing right, cut from deep cobalt blue glass (#0047AB), with crisp polygonal facets catching a bright sapphire-blue rim light (#2E6BFF) along its top-left edges. Subtle cool glow radiating from the gem onto the dark background. Flat modern logo style, sharp clean edges, high contrast, centered composition with generous margins, no text, no letters, no watermark. Looks crisp at small avatar sizes.

(Avatars render at 98px — keep it text-free; the gem-play-button IS the identity.)

## Image-gen prompt — banner (2048×1152, safe area = center 1235×338)

> A wide YouTube channel banner, 2048x1152, on a near-black carbon background (#101418). Centered horizontally and vertically (all key elements within the middle safe zone): the bold all-caps wordmark "C0BALT CUT" in a heavy geometric sans-serif, platinum white (#E8ECF1), wide letter spacing — the zero in "C0BALT" is rendered as a faceted cobalt-blue gemstone (#0047AB) with a play-button triangle cut into its center, glowing sapphire blue (#2E6BFF). Beneath the wordmark in small spaced capitals: "ZERO FILLER. ALL PAYOFF." Running horizontally behind the text, a thin audio waveform in dim cobalt blue that is cleanly sliced in the middle — the severed segment near the wordmark glows bright sapphire. Minimal, premium, sharp; cinematic dark-tech aesthetic; no other colors, no clutter, no watermark.

If the model mangles the lettering (common), regenerate the same prompt with `no text` and overlay the wordmark yourself — the waveform-sliced-by-light composition is the part worth keeping.

## Where the brand touches the pipeline

- `generate-title` / `title-transition`: title cards on Carbon Black with Platinum type and a Sapphire accent rule.
- `like-subscribe-overlay`: CTA card in Cobalt/Sapphire, gem-play-button mark next to "Subscribe".
- `burn-subtitles`: keep karaoke highlight in Sapphire Glow (#2E6BFF).
