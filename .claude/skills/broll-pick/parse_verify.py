#!/usr/bin/env python3
import json, re, sys

reply = open(sys.argv[1]).read()
m = re.search(r"\{.*\}", reply, re.DOTALL)
out = {"match": False, "best": 0}
if m:
    try:
        obj = json.loads(m.group(0))
        if obj.get("match") is True:
            best = int(obj.get("best", 0))
            out = {"match": True, "best": best if best in (0, 1, 2) else 0}
    except Exception:
        pass
print(json.dumps(out))
