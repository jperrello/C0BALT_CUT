#!/usr/bin/env python3
# never fails: invalid/missing picks fall back to the least-used valid style
# (deterministic round-robin seeded by current-run + recent-history usage).
import json, os, re, sys

reply_path, segments_path = sys.argv[1:3]
recent_path = sys.argv[3] if len(sys.argv) > 3 else ""

STYLES = ["slam", "typewriter", "glitch", "bounce", "cinematic"]

doc = json.load(open(segments_path))
segs = doc.get("shorts", [])

picks = {}
text = ""
if reply_path and os.path.exists(reply_path):
    text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
if m:
    try:
        for v in json.loads(m.group(0)).get("styles", []):
            if v.get("style") in STYLES:
                picks[int(v["span"])] = v
    except Exception as e:
        print(f"pick-title-styles: bad JSON in reply ({e}); falling back", file=sys.stderr)
if not picks:
    print("pick-title-styles: no usable picks in reply; round-robin fallback", file=sys.stderr)

used = {s: 0 for s in STYLES}
if recent_path and os.path.exists(recent_path):
    for l in open(recent_path):
        l = l.strip()
        if l in used:
            used[l] += 1
for v in picks.values():
    used[v["style"]] += 1


def least():
    return min(STYLES, key=lambda s: (used[s], STYLES.index(s)))


out = []
for i, s in enumerate(segs):
    s = dict(s)
    v = picks.get(i)
    if v:
        s["title_style"] = v["style"]
        s["title_style_note"] = str(v.get("note", ""))[:200]
    else:
        pick = least()
        used[pick] += 1
        s["title_style"] = pick
        s["title_style_note"] = "fallback (least recently used)"
    out.append(s)

doc["shorts"] = out
json.dump(doc, sys.stdout, indent=2)

if recent_path:
    hist = []
    if os.path.exists(recent_path):
        hist = [l.strip() for l in open(recent_path) if l.strip()]
    hist += [s["title_style"] for s in out]
    open(recent_path, "w").write("\n".join(hist[-15:]) + "\n")

print(f"pick-title-styles: {len(out)} span(s): "
      + ", ".join(f'{i}={s["title_style"]}' for i, s in enumerate(out)), file=sys.stderr)
