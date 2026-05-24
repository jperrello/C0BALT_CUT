#!/usr/bin/env python3
import json, re, sys

reply_path, transcript_path = sys.argv[1:3]

FILLERS = {"so","and","but","um","uh","like","well","okay","ok","basically",
           "actually","anyway","you","i","i'm","im","my","me","we","us"}
BANNED_CHARS = set('?!:"“”‘’')

def clean(text):
    text = text.strip()
    text = text.strip('"“”‘’\'')
    text = re.sub(r"\s+", " ", text)
    return text

def usable(text):
    if not text:
        return False
    if any(c in BANNED_CHARS for c in text):
        return False
    words = text.split()
    if not (1 <= len(words) <= 7):
        return False
    return True

def fallback():
    tx = json.load(open(transcript_path))
    words = []
    for w in tx.get("words", []):
        t = str(w.get("w", "")).strip().strip(".,?!")
        if t and t.lower() not in FILLERS:
            words.append(t)
        if len(words) >= 5:
            break
    if not words:
        for s in tx.get("segments", []):
            for t in str(s.get("text", "")).split():
                tt = t.strip(".,?!")
                if tt and tt.lower() not in FILLERS:
                    words.append(tt)
                if len(words) >= 5:
                    break
            if len(words) >= 5:
                break
    if not words:
        return "SHORT"
    return " ".join(words).upper()

raw = ""
try:
    raw = open(reply_path).read()
except Exception:
    pass

# Take the first non-empty line.
candidate = ""
for line in raw.splitlines():
    s = clean(line)
    if s:
        candidate = s
        break

candidate = candidate.upper()

if usable(candidate):
    print(candidate)
else:
    fb = fallback()
    print(fb, end="\n")
    print(f"generate-title: reply unusable ({candidate!r}); fallback {fb!r}", file=sys.stderr)
