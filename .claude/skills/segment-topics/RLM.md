# segment-topics RLM map-reduce — design + decision record

The rlm-assisted path of `segment-topics` (used on long sources: `RLM_TOPICS=1`, or
auto when duration ≥ `RLM_TOPICS_MIN_SEC`=1500s) fans the FULL-resolution transcript
out to per-chunk sub-LLMs so the back half of a 25–90min source is never compressed
away. The "orchestrator" is the live Claude pane that runs `build_rlm_prompt.py`'s
instructions: it dispatches one `rlm-segment-subcall` per chunk (MAP), verifies +
re-dispatches gappy chunks, then synthesizes one whole-video result (REDUCE) →
`topics.json` + `candidates.hint.json`.

Everything that CAN be deterministic lives in Python (`build_rlm_prompt.py`,
`parse_reply.py`, `parse_candidates.py`) so the agentic surface stays small and the
parsers always emit valid output even on a sloppy reply.

Source audit of tactics to steal: `~/.claude/crew/geoff/rlm-findings.md` (rcc +
brainqub3/RLM). The numbering below (`geoff #N`) is that doc's ranking.

## Adopted

| # | Tactic | Bead | Where |
|---|---|---|---|
| 1+5 | **Seam-aware chunking + overlap** — cut windows on natural seams (long silences = large inter-segment gaps; topic-shift cue phrases) within a search radius of the target size, with ~45s overlap so a straddling moment appears whole in one window. Replaces blind fixed 600s windows. | shorts-mk4 | `build_rlm_prompt.py` (`seam_score`, chunking loop); knobs `RLM_SEAM_OVERLAP`/`RLM_SEAM_GAP`/`RLM_SEAM_WINDOW` |
| 4 | **Model routing** — the per-chunk subcall (topic tiling is cheap, but the candidate "most clip-worthy moment" judgment is the quality call Haiku under-rates) runs on **Sonnet** by default. Implemented as a PROJECT-LOCAL agent `rlm-segment-subcall` (model: sonnet) so the global `rlm-subcall` (used by `/rlm` and other projects) stays Haiku; `RLM_SUBCALL_MODEL` overrides per-dispatch. | shorts-j2y | `.claude/agents/rlm-segment-subcall.md`; `build_rlm_prompt.py` MAP block |
| 2 | **Coverage-verify + re-dispatch** — the orchestrator is told to confirm each chunk parsed and its topics TILE its window, and to re-dispatch any empty/garbled/gappy chunk before REDUCE. Safety net: `parse_reply.py` warns on a residual coverage gap and forces contiguity regardless. | shorts-upk | `build_rlm_prompt.py` VERIFY block; `parse_reply.py` gap diagnostic |
| 3 | **Confidence-ranked candidates** — each candidate carries `confidence` (0–1 standalone-clip-worthiness) from the subcall + REDUCE; `parse_candidates.py` ranks the hint by it, and `pick-segments` surfaces RANKED hints (not flat). | shorts-7mk | `build_rlm_prompt.py` query/REDUCE; `parse_candidates.py`; `pick-segments/build_prompt.py` |
| 6 | **Chunk MAP cache** — chunks + per-chunk results live in `work/<id>/rlm/` (stable, not tmp), keyed by content hash (`chunk_NN.<sha1>.json`). A re-run embeds unchanged chunks' cached results into the prompt and only lists changed/new chunks for dispatch; stale-hash files are pruned. | shorts-bui | `build_rlm_prompt.py` (`map_dir`, embed/prune); `segment-topics.sh` (`rlm_dir`) |
| 7 | **Usage / structure log** — `work/<id>/rlm/usage.json` records per-chunk seconds/words/chars/≈input-tokens/hash/cached/model + totals, for tuning chunk size, batch, and model tier. NOTE: true leaf token counts aren't surfaced by the Task-subagent path (unlike brainqub3's headless `claude -p`), so we log a chars/4 proxy + structure — the data actually available to the orchestrator. | shorts-t9c | `build_rlm_prompt.py`; surfaced by `segment-topics.sh` |

### Cross-chunk threading (epic shorts-0od)
The map-reduce treated every chunk in isolation; a thread that opens in chunk N and pays
off in distant chunk M could never become one short. Proven example (work/df8e838b89, JRE
#2217 Brian Cox): black-hole information paradox setup @524–534s (chunk 0) → payoff
@9740–9762s (chunk 16), ~2.5h apart. `assemble.py` already cuts+concats non-contiguous
ranges range-agnostically, so construction was solved — only detection + permission were
missing.

- **Mechanism A — reduce-level threading (detection)** `shorts-qw3`: REDUCE scans all
  candidates + open_threads + callbacks for genuine setup→payoff / callback / escalation
  / contradiction threads and emits COMPOUND candidates `{thread, kind, cuts[2-3], bridge,
  confidence}`. Works on today's data, zero map change. `parse_candidates.py` validates +
  emits them; `pick-segments/build_prompt.py` shows a CROSS-CHUNK THREADS block.
- **Mechanism B — map-emitted thread hints** `shorts-slr`: each subcall also returns
  `open_threads` (setups it opens but doesn't resolve) + `callbacks` (explicit references
  back). The generic `rlm-subcall` schema already had `suggested_next_queries`+`missing`
  for this; our custom query had dropped them — re-added. REDUCE matches mention→origin.
- **Permission — `thread` span type** `shorts-8la`: a pick marked `"thread": true` with
  ≥2 cuts bypasses the single-topic drop in `pick-segments/parse_reply.py`; being
  multi-cut it already bypasses `verify-coherence` tightening. Guardrails downstream
  (verify-completeness, verify-bookends, director-pass vision QA) catch a bad stitch.
  Capped at 3 cuts.

### Output
- **Selection report** `shorts-aun`: `selection-report` writes `output/<slug>/_selection.json`
  (shipped shorts + considered-not-shipped RLM menu + topics) so the candidates the
  pipeline passed over are visible next to the produced shorts.

## Evaluated and NOT adopted (shorts-9b0)

- **geoff #8 — true recursion (depth > 1).** brainqub3's `rlm_query` spawns nested
  RLM-with-skill (`RLM_DEPTH`/`RLM_MAX_DEPTH`); rcc runs max_depth 2–3. **Low payoff for
  us.** A 25–90min transcript is only ~3–9 windows after seam-aware chunking; a single
  depth-1 map-reduce already covers it. Recursion exists for 500-document-scale subtasks
  where one chunk is itself too big to read — not our regime. Adopting it would add a
  whole orchestration layer (depth budget, nested skill bootstrap, recursion guards) for
  no quality gain. **Revisit only if we ingest much larger corpora** (e.g. an entire
  channel's back-catalogue as one context).

- **geoff #9 — learned activation gating.** rcc's `PatternClassifier.should_activate`
  scores query+context complexity to decide whether to even run RLM. We already gate on a
  hard, legible `duration ≥ RLM_TOPICS_MIN_SEC` rule (with `RLM_TOPICS=0/1` override). A
  learned complexity score is marginal over a duration threshold for a single content type
  (long-form spoken video) and adds opacity. **Skip** — the hard rule is sufficient and
  debuggable. Revisit only if source types diversify enough that duration stops predicting
  "needs the full-resolution read".
