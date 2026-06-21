import sys, json, re

# Parse claude's rubric reply into {hook_payoff,open_loop,cold_context} ints 0-10.
# Deterministic fallback (neutral 5s) when the reply doesn't parse.
reply_path = sys.argv[1]

text = ""
try:
    text = open(reply_path).read()
except Exception:
    text = ""

out = {"hook_payoff": 5, "open_loop": 5, "cold_context": 5}
m = re.search(r"\{.*\}", text, re.S)
if m:
    try:
        d = json.loads(m.group(0))
        for k in out:
            v = d.get(k)
            if isinstance(v, (int, float)):
                out[k] = int(max(0, min(10, round(v))))
    except Exception:
        pass

json.dump(out, sys.stdout)
