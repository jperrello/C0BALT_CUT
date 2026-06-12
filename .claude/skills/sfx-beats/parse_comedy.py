#!/usr/bin/env python3
# validate Claude's comedy-beat reply -> plan.json {ok, events:[{t,type}]}.
import json, re, sys

reply_path, dur = sys.argv[1], float(sys.argv[2])

text = open(reply_path).read()
m = re.search(r"\{.*\}", text, re.S)
if not m:
    json.dump({"ok": False, "reason": "no JSON in reply", "events": []}, sys.stdout)
    sys.exit(0)
try:
    beats = json.loads(m.group(0)).get("beats", [])
except ValueError:
    json.dump({"ok": False, "reason": "bad JSON", "events": []}, sys.stdout)
    sys.exit(0)

TYPES = {"boom", "scratch", "ding"}
events = []
for b in beats if isinstance(beats, list) else []:
    try:
        t = float(b["t"])
        typ = str(b.get("type", "")).strip().lower()
    except (KeyError, TypeError, ValueError):
        continue
    if typ not in TYPES:
        continue
    if not (1.0 <= t <= dur - 0.5):
        continue
    if any(abs(t - e["t"]) < 2.5 for e in events):
        continue
    events.append({"t": round(t, 3), "type": typ})
    if len(events) >= 4:
        break

events.sort(key=lambda e: e["t"])
json.dump({"ok": bool(events), "reason": f"{len(events)} beat(s)", "events": events},
          sys.stdout)
