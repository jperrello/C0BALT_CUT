#!/usr/bin/env python3
import os, re, sys
from datetime import date

SECTIONS = [
    ("topic", "segment-topics, pick-segments",
     "Did this topic earn your interest on its own?"),
    ("hook", "pick-segments, bookend-trim",
     "Did the first 3 seconds grab you? Did it end clean, not mid-thought?"),
    ("title", "generate-title",
     "Would the title card stop a cold scroller? Still honest after watching?"),
    ("captions", "chunk-captions, burn-subtitles",
     "Readable, well-chunked, in sync?"),
    ("broll", "broll-pick, broll-composite",
     "Did cutaways match the story's tone? Right density and timing?"),
    ("music", "pick-mood, bg-music",
     "Does the song fit the theme? Sitting at the right level?"),
    ("pacing", "trim-filler, tighten-pace",
     "Any dead air, jarring cuts, or rushed moments?"),
]


def grab(path):
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def render(short, clip):
    head = f"""---
source: {os.path.basename(os.path.dirname(os.path.abspath(short)))}
short: {os.path.basename(short)}
title: {grab(clip + ".title.txt") if clip else ""}
mood: {grab(clip + ".mood.txt") if clip else ""}
generated: {date.today().isoformat()}
reviewed:
---

Score 1-5 (blank = no opinion). The why line is the real signal: always
fill it in for any 1, 2, or 5. Set `reviewed:` to today's date when done.
Ingest ignores forms with an empty reviewed field.
"""
    parts = [head]
    for key, owns, q in SECTIONS:
        parts.append(f"\n## {key}\n<!-- owns: {owns} -->\n{q}\nscore:\nwhy:\n")
    parts.append("\n## overall\nverdict (post / rework / kill):\nwhy:\n")
    return "".join(parts)


def emit(short, clip=""):
    path = re.sub(r"\.mp4$", "", short) + ".feedback.md"
    if os.path.exists(path):
        print(f"skip (exists): {path}")
        return
    open(path, "w").write(render(short, clip))
    print(path)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--scan":
        root = args[1] if len(args) > 1 else "./output"
        for dirpath, _, files in os.walk(root):
            for f in sorted(files):
                if f.endswith(".mp4"):
                    emit(os.path.join(dirpath, f))
        sys.exit(0)
    emit(args[0], args[1] if len(args) > 1 else "")
