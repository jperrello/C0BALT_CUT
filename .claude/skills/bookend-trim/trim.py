#!/usr/bin/env python3
# snap each segment's [t0, t1] to a sentence boundary. whisper.cpp strips
# punctuation in this project's transcribe config, so we use inter-word silence
# gaps as a proxy: a pause >= GAP_THRESHOLD seconds reliably marks a clause /
# sentence break in conversational speech.
import json, sys

GAP_THRESHOLD = 0.45  # seconds; >= this = sentence boundary
START_PAD = 0.10
END_PAD = 0.15


def boundaries(words):
    # returns (sentence_starts, sentence_ends) as parallel lists of timestamps.
    # a "start" is the t0 of the first word of a sentence; an "end" is the t1 of
    # the last word of a sentence.
    starts, ends = [], []
    n = len(words)
    for i, w in enumerate(words):
        prev_gap = w['t0'] - words[i - 1]['t1'] if i > 0 else float('inf')
        next_gap = words[i + 1]['t0'] - w['t1'] if i < n - 1 else float('inf')
        if prev_gap >= GAP_THRESHOLD:
            starts.append(w['t0'])
        if next_gap >= GAP_THRESHOLD:
            ends.append(w['t1'])
    return starts, ends


def snap(starts, ends, t0, t1, extend):
    # END: pick the sentence-end closest to t1 within [t1-extend, t1+extend],
    # preferring extension over pulling back.
    end_cands = [e for e in ends if t1 - extend <= e <= t1 + extend]
    new_t1, end_note = t1, None
    if end_cands:
        best = min(end_cands, key=lambda e: (e < t1, abs(e - t1)))
        new_t1 = best + END_PAD
        end_note = f"t1 {t1:.2f}->{new_t1:.2f}"

    # START: pick the sentence-start closest to t0 within [t0-extend, t0+extend],
    # preferring pulling back over pushing forward.
    start_cands = [s for s in starts if t0 - extend <= s <= t0 + extend]
    new_t0, start_note = t0, None
    if start_cands:
        best = min(start_cands, key=lambda s: (s > t0, abs(s - t0)))
        new_t0 = max(0.0, best - START_PAD)
        start_note = f"t0 {t0:.2f}->{new_t0:.2f}"

    if new_t1 - new_t0 < 1.0:
        return t0, t1, "rejected: collapsed below 1s"
    notes = [n for n in (start_note, end_note) if n]
    return new_t0, new_t1, "; ".join(notes) if notes else "no boundary in window"


def main():
    segs_path, tx_path, out_path = sys.argv[1:4]
    extend = float(sys.argv[4]) if len(sys.argv) > 4 else 6.0

    segs = json.load(open(segs_path))
    starts, ends = boundaries(json.load(open(tx_path))['words'])

    for s in segs['shorts']:
        nt0, nt1, note = snap(starts, ends, s['t0'], s['t1'], extend)
        s['t0'], s['t1'] = nt0, nt1
        s['bookend_note'] = note

    json.dump(segs, open(out_path, 'w'), indent=2)
    print(f"bookend-trim: wrote {out_path} ({len(segs['shorts'])} spans)", file=sys.stderr)


if __name__ == '__main__':
    main()
