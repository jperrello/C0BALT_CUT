#!/usr/bin/env python3
# Parse the derive-thesis reply -> thesis.json; deterministic fallback on failure.
import json, re, sys

reply_path, topics_path = sys.argv[1:3]

try:
    topics = json.load(open(topics_path)).get("topics", [])
except (OSError, ValueError):
    topics = []

def fallback():
    # subject = longest chapter's title; threads = the leading chapter titles.
    subj = ""
    if topics:
        longest = max(topics, key=lambda t: (t.get("t1", 0) - t.get("t0", 0)))
        subj = str(longest.get("title", "")).strip()
    threads = [str(t.get("title", "")).strip() for t in topics[:6] if str(t.get("title", "")).strip()]
    return {"subject": subj or "the source video",
            "thesis_sentence": "",
            "key_threads": threads,
            "fallback": True}

try:
    text = open(reply_path).read()
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0)) if m else None
    if not data or not str(data.get("subject", "")).strip():
        raise ValueError("no subject in reply")
    out = {
        "subject": str(data.get("subject", "")).strip()[:120],
        "thesis_sentence": str(data.get("thesis_sentence", "")).strip()[:400],
        "key_threads": [str(x).strip()[:80]
                        for x in (data.get("key_threads") or [])
                        if str(x).strip()][:8],
    }
except (OSError, ValueError, AttributeError, TypeError):
    out = fallback()

json.dump(out, sys.stdout, indent=2)
