#!/usr/bin/env python3
# Parse a batched verify reply into {"<n>": {"match":bool,"best":0|1|2}, ...}.
# Missing/unparseable entries are simply absent (treated as no-match upstream).
import json, re, sys

reply = open(sys.argv[1]).read()
out = {}
m = re.search(r"\{.*\}", reply, re.DOTALL)
if m:
    try:
        obj = json.loads(m.group(0))
        for r in obj.get("results", []) or []:
            try:
                n = int(r.get("n"))
            except Exception:
                continue
            if r.get("match") is True:
                try:
                    b = int(r.get("best", 0))
                except Exception:
                    b = 0
                out[str(n)] = {"match": True, "best": b if b in (0, 1, 2) else 0}
            else:
                out[str(n)] = {"match": False}
    except Exception:
        pass
print(json.dumps(out))
