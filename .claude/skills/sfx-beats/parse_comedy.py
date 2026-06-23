#!/usr/bin/env python3
# validate Claude's comedy-beat reply -> plan.json {ok, events:[{t,type}]}.
import json, os, re, sys

reply_path, dur = sys.argv[1], float(sys.argv[2])

# keep the closing beat SFX-free: no beat may land in (or ring into) the end card.
# this runs PRE-speed, but end-card is composited on the last END_CARD_DUR s of the
# POST-speed clip = the last END_CARD_DUR*SPEED s in THIS timeline — so the guard must
# scale by SPEED, else a payoff "ding" rings over the "FOLLOW FOR MORE" beat. +1.0s
# margin clears the bell's ~0.55s decay so nothing bleeds onto the card (shorts-hdk).
speed = float(os.environ.get("SPEED", "1.25")) if os.environ.get("SPEED_UP", "1") != "0" else 1.0
endcard = 0.0 if os.environ.get("END_CARD", "1") == "0" else float(os.environ.get("END_CARD_DUR", "2.5"))
tail = endcard * speed + (1.0 if endcard > 0 else 0.5)
last = max(1.0, dur - tail)

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
    if not (1.0 <= t <= last):
        continue
    if any(abs(t - e["t"]) < 2.5 for e in events):
        continue
    events.append({"t": round(t, 3), "type": typ})
    if len(events) >= 4:
        break

events.sort(key=lambda e: e["t"])
json.dump({"ok": bool(events), "reason": f"{len(events)} beat(s)", "events": events},
          sys.stdout)
