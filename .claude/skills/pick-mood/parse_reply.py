#!/usr/bin/env python3
import sys, os

reply_path, songs_root = sys.argv[1:3]

try:
    raw = open(reply_path).read().strip()
except Exception:
    raw = ""

# Strip quotes/punctuation and take the first non-empty line.
line = ""
for ln in raw.splitlines():
    s = ln.strip().strip("\"'`* .,:-").strip()
    if s:
        line = s
        break

moods = {
    d for d in os.listdir(songs_root)
    if os.path.isdir(os.path.join(songs_root, d)) and not d.startswith(".")
}

# Case-insensitive match against the live folder list.
match = next((m for m in moods if m.lower() == line.lower()), "")
print(match or "ALL SONGS")
