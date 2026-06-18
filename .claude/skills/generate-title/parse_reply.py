#!/usr/bin/env python3
import json, re, sys

reply_path, transcript_path = sys.argv[1:3]

FILLERS = {"so","and","but","um","uh","like","well","okay","ok","basically",
           "actually","anyway","you","i","i'm","im","my","me","we","us"}
# Punctuation we don't want in a chyron. We STRIP these, we do not reject on them —
# a good title with a stray colon/quote is salvaged, not thrown away to gibberish.
STRIP_CHARS = '?!:"“”‘’.'

def clean(text):
    text = text.strip()
    text = text.strip('"“”‘’\'')
    text = re.sub(r"\s+", " ", text)
    return text

# Salvage a reply line into a usable title instead of discarding it:
# strip banned punctuation, drop trailing punctuation, cap at 7 words.
# Returns "" only when nothing title-like survives.
def salvage(text):
    text = "".join(" " if c in STRIP_CHARS else c for c in text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if not words:
        return ""
    if len(words) > 7:
        words = words[:7]
    return " ".join(words).upper()

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

# A well-behaved reply is a single title line, but Claude sometimes prefixes a
# stray sentence ("Here's the title:"). Walk lines and take the first that
# salvages into a plausible title — prefer the LAST non-empty line if none of the
# earlier ones look like a title (model often lands the answer last).
lines = [clean(l) for l in raw.splitlines()]
lines = [l for l in lines if l]

candidate = ""
for s in lines:
    cand = salvage(s)
    # Heuristic: a real title is short and not an obvious instruction echo.
    if cand and not s.lower().startswith(("here", "title", "sure", "the title")):
        candidate = cand
        break

if not candidate and lines:
    candidate = salvage(lines[-1])

if candidate:
    print(candidate)
else:
    fb = fallback()
    print(fb)
    print(f"generate-title: reply empty/unusable; fallback {fb!r}", file=sys.stderr)
