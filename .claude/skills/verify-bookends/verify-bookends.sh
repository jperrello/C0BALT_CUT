#!/usr/bin/env bash
# verify-bookends: ask Claude (vision) whether the first/last 1.5s of a short
# are clean, and if not propose an inward-only trim.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

in_clip="${1:-}"
in_tx="${2:-}"
out_json="${3:-}"

if [[ -z "$in_clip" || -z "$in_tx" || -z "$out_json" ]]; then
  echo "usage: verify-bookends.sh <in_clip> <in_trimmed_transcript> <out_decision_json>" >&2
  exit 2
fi
[[ -f "$in_clip" ]] || { echo "verify-bookends: clip not found: $in_clip" >&2; exit 2; }
[[ -f "$in_tx"   ]] || { echo "verify-bookends: transcript not found: $in_tx" >&2; exit 2; }

here="$(cd "$(dirname "$0")" && pwd)"
meta="$out_json.vbmeta"
in_mtime="$(stat -f %m "$in_clip" 2>/dev/null || stat -c %Y "$in_clip")"
tx_mtime="$(stat -f %m "$in_tx"   2>/dev/null || stat -c %Y "$in_tx")"
sig="$in_mtime|$tx_mtime|v4-ctxgate"

if [[ -f "$out_json" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "verify-bookends: cache hit at $out_json" >&2
  cat "$out_json"; exit 0
fi

mkdir -p "$(dirname "$out_json")"

# Disable switch
if [[ "${VERIFY_BOOKENDS:-1}" == "0" ]]; then
  echo '{"action":"keep","reason":"disabled via VERIFY_BOOKENDS=0","context_pass":true,"first_payoff_offset":null}' > "$out_json"
  printf '%s' "$sig" > "$meta"
  cat "$out_json"; exit 0
fi

dur="$(ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 "$in_clip")"
if [[ -z "$dur" ]] || ! python3 -c "import sys; sys.exit(0 if float('$dur')>0 else 1)" 2>/dev/null; then
  echo '{"action":"keep","reason":"could not read duration","context_pass":true,"first_payoff_offset":null}' > "$out_json"
  printf '%s' "$sig" > "$meta"
  cat "$out_json"; exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Compute the 6 frame timestamps in one python call
read -r HEAD_T0 HM HEAD_T1 TAIL_T0 TM TAIL_T1 < <(python3 -c "
dur=float('$dur'); W=1.5
h0=0.0; h1=min(W,dur); hm=(h0+h1)/2
t0=max(0.0,dur-W); t1=max(0.0,dur-0.05); tm=(t0+t1)/2
print(f'{h0:.3f} {hm:.3f} {h1:.3f} {t0:.3f} {tm:.3f} {t1:.3f}')")

frame_at() {
  ffmpeg -y -hide_banner -loglevel error -ss "$1" -i "$in_clip" -frames:v 1 -vf scale=480:-2 "$2" 2>/dev/null || true
}

frame_at "$HEAD_T0" "$tmp/h1.jpg"
frame_at "$HM"      "$tmp/h2.jpg"
frame_at "$HEAD_T1" "$tmp/h3.jpg"
frame_at "$TAIL_T0" "$tmp/t1.jpg"
frame_at "$TM"      "$tmp/t2.jpg"
frame_at "$TAIL_T1" "$tmp/t3.jpg"

# Build head and tail strips (3 frames side-by-side each)
if ls "$tmp"/h*.jpg >/dev/null 2>&1 && ls "$tmp"/t*.jpg >/dev/null 2>&1; then
  ffmpeg -y -hide_banner -loglevel error \
    -i "$tmp/h1.jpg" -i "$tmp/h2.jpg" -i "$tmp/h3.jpg" \
    -filter_complex "[0:v][1:v][2:v]hstack=inputs=3" "$tmp/head.jpg" 2>/dev/null || true
  ffmpeg -y -hide_banner -loglevel error \
    -i "$tmp/t1.jpg" -i "$tmp/t2.jpg" -i "$tmp/t3.jpg" \
    -filter_complex "[0:v][1:v][2:v]hstack=inputs=3" "$tmp/tail.jpg" 2>/dev/null || true
fi

# Build transcript snippets
python3 - "$in_tx" "$HEAD_T1" "$TAIL_T0" "$dur" > "$tmp/snip.json" <<'PY'
import json, sys
tx = json.load(open(sys.argv[1]))
head_t1 = float(sys.argv[2])
tail_t0 = float(sys.argv[3])
dur = float(sys.argv[4])
words = tx.get("words", [])

def words_in(a, b):
    return [w for w in words if w["t0"] >= a - 1e-3 and w["t1"] <= b + 1e-3]

head_words = words_in(0.0, head_t1)
tail_words = words_in(tail_t0, dur)

def fmt(ws):
    return " ".join(f"[{w['t0']:.2f}-{w['t1']:.2f}]{w['w']}" for w in ws)

# also list word boundaries Claude is allowed to snap to
boundaries = sorted({round(w["t0"], 3) for w in words} | {round(w["t1"], 3) for w in words})
head_bounds = [b for b in boundaries if b <= head_t1 + 0.5]
tail_bounds = [b for b in boundaries if b >= tail_t0 - 0.5]

# Mid-sentence opener guard: if the FIRST spoken word is a sentence-fragment
# continuation, find a clean forward snap (first word after a >=0.25s gap)
# within ~2s that still leaves a >=15s clip. Surfaced to Claude AND enforced
# deterministically downstream, so "of picturing what's happened..." can't open.
FRAGMENT_OPENERS = {"of","than","nor","whom","whose","thereof","therein",
                    "wherein","whereby","whereas","and","but","so","because"}
open_words = words_in(0.0, min(3.0, dur))
first = open_words[0] if open_words else None
first_word = first["w"].strip(".,?!").lower() if first else ""
bad_open = first_word in FRAGMENT_OPENERS
open_snap = None
if bad_open and first is not None:
    prev = first["t1"]
    for w in open_words[1:]:
        if w["t0"] - prev >= 0.25 and w["t0"] <= 2.0 and (dur - w["t0"]) >= 15.0:
            open_snap = round(w["t0"], 3)
            break
        prev = w["t1"]

# Cold-viewer context gate: the FIRST DELIVERED SENTENCE must stand alone for a
# stranger. Surface the opening few seconds of words + the early sentence-start
# boundaries (first word after a >=0.30s pause) so Claude can pick a clean
# context_snap_t0 within the payoff budget. payoff_budget is the hard
# time-to-first-payoff window (default 3.0s) parse_reply uses to bound the snap.
PAYOFF_BUDGET = float(__import__("os").environ.get("VB_PAYOFF_BUDGET", "3.0"))
budget_words = words_in(0.0, min(PAYOFF_BUDGET + 2.0, dur))
context_starts = []
prev = None
for w in budget_words:
    if prev is None or (w["t0"] - prev) >= 0.30:
        if 0.0 < w["t0"] <= PAYOFF_BUDGET and (dur - w["t0"]) >= 15.0:
            context_starts.append(round(w["t0"], 3))
    prev = w["t1"]

json.dump({
    "dur": dur,
    "head_t1": head_t1,
    "tail_t0": tail_t0,
    "head_text": fmt(head_words),
    "tail_text": fmt(tail_words),
    "head_boundaries": head_bounds,
    "tail_boundaries": tail_bounds,
    "first_word": first_word,
    "bad_open": bad_open,
    "open_snap": open_snap,
    "payoff_budget": PAYOFF_BUDGET,
    "open_text": fmt(budget_words),
    "context_starts": context_starts,
}, sys.stdout)
PY

snip="$(cat "$tmp/snip.json")"
PAYOFF_BUDGET_DISP="$(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).read())["payoff_budget"])' "$tmp/snip.json")"

prompt_file="$tmp/prompt.txt"
{
  cat <<EOF
You are reviewing the OPENING (first 1.5s) and CLOSING (last 1.5s) of a finished podcast short. You see two image strips (3 frames each, left-to-right covering the 1.5s window) plus the word-timed transcript around each end.

Clip duration: ${dur} seconds.
Head window: 0.0 – ${HEAD_T1}s
Tail window: ${TAIL_T0} – ${dur}s

Head transcript: $(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).read())["head_text"])' "$tmp/snip.json")
Tail transcript: $(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).read())["tail_text"])' "$tmp/snip.json")

Allowed head boundaries (snap t0 to one of these): $(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).read())["head_boundaries"])' "$tmp/snip.json")
Allowed tail boundaries (snap t1 to one of these): $(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).read())["tail_boundaries"])' "$tmp/snip.json")
First spoken word: $(python3 -c 'import json,sys; d=json.loads(open(sys.argv[1]).read()); print(repr(d.get("first_word","")), "(MID-SENTENCE FRAGMENT)" if d.get("bad_open") else "(ok)")' "$tmp/snip.json")

Opening words (the first ~${PAYOFF_BUDGET_DISP}s of the delivered clip): $(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).read())["open_text"])' "$tmp/snip.json")
Allowed context-snap boundaries (sentence starts within the payoff budget): $(python3 -c 'import json,sys; print(json.loads(open(sys.argv[1]).read())["context_starts"])' "$tmp/snip.json")

You are checking FIVE things:

(1) CLEANLINESS — opening and closing must be free of partial syllables,
    co-speaker interjections, breath cutoffs, and off-shot frames.

(2) OPENING-HOOK STRENGTH — the first ~3 seconds is the swipe-away gate.
    A scrolling stranger who knows nothing about the source must have a
    reason to stay past second 3. The opening fails the hook test if:
      - The first words are throat-clearing or pure setup ("so, basically,
        what we wanted to talk about today is...")
      - The opening makes no concrete claim, names no subject, asks no
        specific question, and offers no immediate visual interest.
    If the opening is weak BUT a stronger hook line exists within the
    first ~3 seconds of the clip (a concrete claim, named subject, or
    specific question), propose an inward t0 snap to that line's
    starting word boundary. If no stronger line exists nearby, keep —
    do NOT drop for hook-weakness alone; cleanliness drops still apply.

(3) PAYOFF LANDING — if the tail window contains a clear PAYOFF (the
    punchline word, the surprising number, the reveal that the rest of
    the clip builds toward), the clip should END right after that
    payoff word, not at the next sentence boundary. Dead air after the
    payoff costs retention. If you see a payoff word in the tail
    transcript followed by trailing "yeah", "so anyway", filler, or
    silence, propose a t1 = (payoff word's end timestamp) + 0.08s,
    snapped to the nearest allowed tail boundary at or just past it.
    If the tail has no discrete payoff (continuous info), keep current
    behavior — only trim for cleanliness.

(4) MID-SENTENCE START — if the first spoken word is a sentence fragment
    (a dangling preposition or conjunction like "of", "than", "and",
    "because" with no subject), the clip opens mid-thought and a scrolling
    stranger hears a scrap of a sentence. Snap t0 FORWARD (inward only) to
    the first word that begins a clean, self-contained phrase, keeping the
    clip >= 15s. This is part of the swipe-away gate.

(5) COLD-VIEWER CONTEXT — the FIRST DELIVERED SENTENCE must stand alone for
    a complete stranger who knows nothing about the source. Set context_pass
    to false if the opening sentence:
      - opens on a DEPENDENT CLAUSE ("when you were making new builds...",
        "which is why...", "after that happened...") with no main clause
        yet spoken;
      - uses a PRONOUN with no on-screen referent ("it was crazy", "they
        told me", "that changed everything", "he said", "she did", "this
        is the part") where "it/they/that/this/he/she" points at something
        the viewer never saw;
      - is a SENTENCE FRAGMENT (no subject+verb that completes a thought);
      - is FLAT THROAT-CLEARING SETUP with no curiosity gap — a plain
        statement of circumstance that promises nothing ("i've got dms on
        instagram", "so we were just hanging out", "i woke up that day").
    Also enforce a HARD TIME-TO-FIRST-PAYOFF budget of ~${PAYOFF_BUDGET_DISP}s:
    report first_payoff_offset = seconds from the delivered open to where
    the TURN/PAYOFF lands (the curiosity gap opens, a concrete claim/number/
    question arrives). If the turn does NOT land within ~${PAYOFF_BUDGET_DISP}s
    AND a stronger context-bearing line exists earlier within budget,
    context_pass is false.
    When context_pass is false, set context_snap_t0 to the START TIMESTAMP
    (a word's t0 from the opening words above) of the next self-contained,
    context-bearing sentence — prefer one of the allowed context-snap
    boundaries, but ANY word-start works since tighten-pace has collapsed
    the audio pauses. It MUST be STRICTLY within the payoff budget (never
    past it, never past the hook). Leave context_snap_t0 null when it
    passes or when no in-budget word-start fixes it.

Decide:
- "keep" — all three checks pass.
- "trim" — propose INWARD-ONLY new t0 and/or t1 that snap to a word
  boundary INSIDE the clip. New t0 >= 0. New t1 <= ${dur}. Never extend
  outward — bookend-trim already had that chance.
- "drop" — cleanliness failure that needs more than 2s of trim to fix.

Hard rules:
- INWARD ONLY. t0 must be >= 0; t1 must be <= ${dur}.
- Removing more than 2.0 seconds total is forbidden — if cleaning the
  bookends needs more than that, return "drop". Hook-weakness alone is
  never a drop reason. Cold-context alone is never a drop reason either —
  it only proposes a forward t0 snap.
- Resulting duration (t1 - t0) must be >= 15 seconds, else return
  "keep" with reason.
- context_snap_t0 must be <= ${PAYOFF_BUDGET_DISP} (the payoff budget) and
  one of the allowed context-snap boundaries, or null.

ALWAYS include context_pass (bool) and first_payoff_offset (seconds, or
null if no discrete turn) on EVERY reply, alongside action. Include
context_snap_t0 only when context_pass is false and a fix is in budget.

Return ONLY one JSON object on a single line — no prose:

  {"action":"keep","reason":"...","context_pass":true,"first_payoff_offset":2.1}
  {"action":"trim","t0":<sec>,"t1":<sec>,"reason":"...","context_pass":false,"first_payoff_offset":3.4,"context_snap_t0":<sec>}
  {"action":"drop","reason":"...","context_pass":true,"first_payoff_offset":null}

EOF
} > "$prompt_file"

if [[ -f "$tmp/head.jpg" && -f "$tmp/tail.jpg" ]]; then
  {
    echo
    echo "HEAD strip (read this image with your Read tool): $tmp/head.jpg"
    echo "TAIL strip (read this image with your Read tool): $tmp/tail.jpg"
  } >> "$prompt_file"
fi

reply_file="$tmp/reply.txt"
run_claude_step verify-bookends "$prompt_file" "$reply_file" 2>"$tmp/claude.err" || {
  cat "$tmp/claude.err" >&2
  echo '{"action":"keep","reason":"claude failed","context_pass":true,"first_payoff_offset":null}' > "$out_json"
  printf '%s' "$sig" > "$meta"
  cat "$out_json"; exit 0
}

# parse + validate (standalone, unit-testable; folds context + fragment snaps)
python3 "$here/parse_reply.py" "$reply_file" "$dur" "$out_json" "$tmp/snip.json"

printf '%s' "$sig" > "$meta"
cat "$out_json"
