---
name: start
description: Run the shorts pipeline across long-lived tmux panes. /start <youtube-url> for a fresh run, or /start <source-id> to reuse an already-ingested video. Each phase shows its progress in the foreground; tmux attach -t <pane> to inspect any phase live.
allowed-tools: Bash
user-invocable: true
---

# /start

Top-level entry point for the shorts pipeline. Fans the work across
named tmux panes so you can `tmux attach -t shorts-<id>-<phase>-<n>` to
watch any Claude lane (or ffmpeg run) live. Semantic panes are long-lived:
they preserve context within one source/span and are cleared at lane
boundaries so unrelated clips do not pollute later decisions.

## Invoke

```
/start <youtube-url>                       # fresh ingest + full pipeline
/start <youtube-id>                        # bare 11-character YouTube IDs are accepted
/start <source-id>                         # reuse already-ingested work/<id>/
/start <id-or-url> <id-or-url> ...         # batch — process each sequentially
```

In batch mode each video's tmux panes are torn down before the next
starts (clean state per video). After a successful run on a YouTube
ID, `videos.edited_at` is stamped in the mcptube SQLite DB so
already-edited videos are easy to filter out.

The orchestrator preflights the mcptube MCP server at
`http://127.0.0.1:9093/mcp` (override with `$MCPTUBE_URL`) and aborts
with instructions if it's unreachable. Set `SHORTS_N`, `SHORTS_DMIN`,
`SHORTS_DMAX` to tune span count / duration.

## Pane layout

- `shorts-<id>-srcprep` — bash: ingest + transcribe
- `shorts-<id>-mcptube` — bash: background mcptube add
- `shorts-<id>-analysis` — Claude: topics → picks → coherence
- `shorts-<id>-lane-N` — one per `SHORTS_MAX_PAR`: a lane worker's pooled
  Claude pane, reused across every span that lane pulls (bookend-trim,
  trim-filler, verify-bookends, chunk-captions, broll-pick verifies,
  generate-title, pick-mood — bash skills interleave in the orchestrator).
  `/clear` runs between phases/spans so context never leaks across spans
  and claude processes stay O(max_par), not O(spans).

A lane's pane dies when the lane drains; everything is torn down on run
completion. `shorts.sh` remains as a non-interactive fallback.

## Run

!`./start.sh "$ARGUMENTS"`
