# Geoff recon — v1 hook scorer → v2 port targets

Source: `/crew talk geoff` on 2026-05-05. Saved here for the implementer crew so this doesn't need to be re-derived. (Note: dispatching geoff for an in-repo file diff was a borderline misuse of his lane — he's a *cross-repo* analyst. Future similar work should be done inline by the implementer crew or the parent.)

## (1) v1 symbols to port (`pipeline.py`)

- **`HOOK_WORDS`** (`pipeline.py:39-43`) — 24-word interjection set. Already duplicated in v2 at `pipeline_v2.py:41-45` (identical literal). No port needed; just stop having two copies once the rest lands.
- **`hook_score(segs, rms_clip, start_abs)`** (`pipeline.py:160-172`) — 13 LOC. Computes `1.0*hit + 0.5*qmark + 1.0*early_peak` over first-3s segments. Returns `(float, bool)`. **Missing in v2 entirely.**
- **Two-pass rank pattern** (`pipeline.py:341-354`) — shortlist via `pick(n=N*3)[:N*2]` → transcribe shortlisted only → rescore `key=-(score + 2.0 * hook_score)` → final `pick(n=N)`. **Missing in v2 entirely.**
- **Per-candidate side state** (`pipeline.py:351-352`): writes `c["hook_score"]` and `c["segs"]` onto candidates so the render pass downstream can reuse `segs` without re-transcribing. Worth preserving.
- **Result-meta fields** (`pipeline.py:375-376`): `hook_score`, `rank_score` exposed in output JSON. v2 currently writes neither.

## (2) v2 merge surface (`pipeline_v2.py`)

- **Insertion point:** `pipeline_v2.py:574-579` — current flow is `cands = score_scenes(...)` → `shape_window` loop → `final = pick(cands, n=args.n)`. The two-pass replaces `pick(cands, n=args.n)` with the v1 shortlist→transcribe→rescore→pick chain.
- `score_scenes` itself (`pipeline_v2.py:496-511`) does NOT change — it's the `energy × log(density)` base score. Hook score is additive on top, applied only to shortlisted candidates after transcription. Same shape as v1.
- `pick()` (`pipeline_v2.py:530-540`) is identical to v1 (n default differs: 3 vs 5) — reuse, no edit. `min_gap=90.0` matches v1's final pick.
- `transcribe` (`pipeline_v2.py:356`) is already present and signature-compatible with v1's call site `(src, cs, ce, tmp)`. Just needs to be invoked inside a `tempfile.TemporaryDirectory()` like `v1:343-352`.
- Per-clip RMS slice for `early_peak`: same pattern as `v1:348-349` — `clip_rms = rms[a:b] if b > a else np.array([0.0])`.
- Result write-out (`pipeline_v2.py:583+`) — extend the `meta.append` with `hook_score` + `rank_score`. Worth a quick read past line 583 once you start.

## (3) v1 helpers v2 lacks

- None beyond `hook_score`. The interjection set (`HOOK_WORDS`) already lives in v2; `pick`, `score_scenes`, `shape_window`, `transcribe`, `audio_rms`, `detect_scenes` are all in v2. No hidden helper dependency — `hook_score` only needs `HOOK_WORDS`, numpy, and the `segs` list shape returned by `transcribe`.
- One non-helper gap worth flagging: v2's `pick` defaults `n=3`; v1's two-pass relies on `n=args.n*3` for shortlist. **Pass explicitly when porting.**

## Scope estimate

~20 LOC port + ~10 LOC wire-up at `pipeline_v2.py:574-579`. No new deps. Single-PR sized.
