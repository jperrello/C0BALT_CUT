---
name: verify-bookends
description: Post-edit verification of a short's opening and closing 1.5s. Claude sees a 3-frame strip from each end plus the trimmed transcript text around each end and returns either {action:keep}, {action:trim,t0,t1} (inward-only), or {action:drop,reason}. Runs after tighten-pace, before fit-vertical. Inward-only — bookend-trim's outward pass already had its chance. Drops the span if cleaning the bookends would require removing more than 2s.
allowed-tools: Bash
user-invocable: true
---

# verify-bookends

Last-line defense before a short is committed to fit-vertical: did the
opening word arrive cleanly, and did the closing word land cleanly? If
either bookend has a breath cutoff, a partial word, a co-speaker
interjection, or a stray frame of the wrong shot, propose an INWARD-ONLY
trim that snaps to the next/previous word boundary inside the clip.

## Invoke

```
.claude/skills/verify-bookends/verify-bookends.sh <input_clip> <input_trimmed_transcript> <out_decision_json> [VERIFY_BOOKENDS=0 to skip]
```

- `input_clip` — post tighten-pace clip
- `input_trimmed_transcript` — post tighten-pace re-timed transcript
- `out_decision_json` — written JSON: `{"action":"keep"}`, `{"action":"trim","t0":<sec>,"t1":<sec>,"reason":...}`, or `{"action":"drop","reason":...}`

Env: `VERIFY_BOOKENDS=0` makes the skill emit `{"action":"keep","reason":"disabled"}` without calling Claude.

## How

1. ffprobe the clip duration.
2. Slice the trimmed transcript text into a head window (first 1.5s) and a tail window (last 1.5s).
3. ffmpeg out a 3-frame strip from each end (start / mid / end of the 1.5s window).
4. Send both strips + both transcript snippets to `claude -p` (vision-enabled) with explicit inward-only rules.
5. Validate the reply: enforce `0 <= t0`, `t1 <= dur`, `t0 >= 0`, `t1 > t0`. If the proposed trim would remove more than 2.0s of clip duration, downgrade to `{"action":"drop"}`. If the proposed trim would shrink the short below 15s, downgrade to `{"action":"keep","reason":"would shrink below 15s"}`.

## Caller contract

`shorts.sh` reads the JSON. If `action=trim`, it issues a second `cut-clip` + `rebase` against the trimmed transcript, then continues to `fit-vertical`. If `action=drop`, it `continue`s the per-span loop and increments the skipped counter. If `action=keep`, no-op.

## Idempotency

Keyed off `(clip mtime, trimmed-transcript mtime)`. Cached decision written next to `<out>.vbmeta`.
