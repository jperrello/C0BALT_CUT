#!/usr/bin/env python3
import json, sys, os

transcript_path, songs_root = sys.argv[1:3]

tx = json.load(open(transcript_path))
segs = tx.get("segments") or []
if segs:
    body = " ".join(s.get("text", "").strip() for s in segs)
else:
    body = " ".join(str(w["w"]).strip() for w in tx.get("words", []))
body = body.strip() or "(empty transcript)"

moods = sorted(
    d for d in os.listdir(songs_root)
    if os.path.isdir(os.path.join(songs_root, d)) and not d.startswith(".")
)
mood_list = "\n".join(f"- {m}" for m in moods)

print(f"""You are choosing the background music mood for a short-form vertical video clip.

The library is organized into mood folders. Pick ONE folder whose vibe best
fits the clip below. All tracks are instrumental — judge on emotional energy
and pacing, not lyrics.

Available moods (use one of these EXACT names):
{mood_list}

Clip transcript:
{body}

Reply with ONLY the mood folder name, exactly as listed. No quotes, no
explanation, no punctuation. Just the name on one line.""")
