#!/usr/bin/env python3
# Parse the verify-bookends Claude reply into the clip_NN.verify.json decision.
# Validates the inward-only / <=2s-removed / >=15s-left invariants, folds the
# cold-viewer context-gate forward snap (context_snap_t0) AND the deterministic
# fragment-opener forward snap (open_snap) into the t0 decision under those same
# guards, and emits context_pass + first_payoff_offset for grade-clip to consume.
#
# usage: parse_reply.py <reply_file> <dur> <out_json> <snip_json>
import json, re, sys

reply_path = sys.argv[1]
dur = float(sys.argv[2])
out_path = sys.argv[3]
snip_path = sys.argv[4] if len(sys.argv) > 4 else ""

try:
    snip = json.load(open(snip_path)) if snip_path else {}
except Exception:
    snip = {}

reply = open(reply_path).read().strip()
m = re.search(r"\{.*\}", reply, re.DOTALL)
raw = {}
if m:
    try:
        raw = json.loads(m.group(0))
    except Exception:
        raw = {}

obj = {"action": raw.get("action", "keep"), "reason": raw.get("reason", "")}
act = obj["action"]
if act == "trim":
    t0 = float(raw.get("t0", 0.0))
    t1 = float(raw.get("t1", dur))
    if t0 < 0:
        t0 = 0.0
    if t1 > dur:
        t1 = dur
    if t1 <= t0:
        obj = {"action": "keep", "reason": "invalid t1<=t0"}
    else:
        removed = (t0 - 0.0) + (dur - t1)
        new_dur = t1 - t0
        if removed > 2.0:
            obj = {"action": "drop", "reason": f"trim would remove {removed:.2f}s (>2.0)"}
        elif new_dur < 15.0:
            obj = {"action": "keep", "reason": f"would shrink below 15s (new_dur={new_dur:.2f})"}
        else:
            obj = {"action": "trim", "t0": round(t0, 3), "t1": round(t1, 3), "reason": obj["reason"]}
elif act == "drop":
    obj = {"action": "drop", "reason": obj["reason"]}
else:
    obj = {"action": "keep", "reason": obj["reason"]}


def snap(target, label):
    # Fold a forward t0 snap into obj under inward-only / <=2s / >=15s guards.
    if not isinstance(target, (int, float)):
        return
    if target <= 0 or obj["action"] == "drop":
        return
    cur_t0 = float(obj["t0"]) if obj["action"] == "trim" else 0.0
    cur_t1 = float(obj["t1"]) if obj["action"] == "trim" else dur
    nt0 = float(target)
    if nt0 <= cur_t0 + 1e-3:
        return
    if (nt0 + (dur - cur_t1)) > 2.0:
        return
    if (cur_t1 - nt0) < 15.0:
        return
    obj["action"] = "trim"
    obj["t0"] = round(nt0, 3)
    obj["t1"] = round(cur_t1, 3)
    obj["reason"] = (obj.get("reason", "") + f" | {label}").strip(" |")


# Context gate: Claude classifies whether the delivered first sentence stands
# alone for a stranger. On fail it proposes context_snap_t0 (forward, within the
# 3s payoff budget). Compose with the deterministic fragment-opener open_snap by
# taking the LARGER justified forward snap (never double-apply).
ctx_pass = raw.get("context_pass")
ctx_pass = bool(ctx_pass) if isinstance(ctx_pass, bool) else True

payoff = raw.get("first_payoff_offset")
if not isinstance(payoff, (int, float)):
    payoff = None

ctx_snap = raw.get("context_snap_t0")
ctx_snap = float(ctx_snap) if isinstance(ctx_snap, (int, float)) and ctx_snap > 0 else None

osnap = snip.get("open_snap")
osnap = float(osnap) if snip.get("bad_open") and isinstance(osnap, (int, float)) and osnap > 0 else None

# Bound the context snap to the 3s payoff budget so we never blow past the hook.
budget = float(snip.get("payoff_budget", 3.0))
if ctx_snap is not None and ctx_snap > budget + 1e-3:
    ctx_snap = None

best = max([s for s in (ctx_snap, osnap) if s is not None], default=None)
if best is not None:
    label = "fwd off cold-context opener" if ctx_snap is not None and best == ctx_snap else "fwd off mid-sentence opener"
    snap(best, label)

obj["context_pass"] = ctx_pass
obj["first_payoff_offset"] = round(float(payoff), 3) if payoff is not None else None

with open(out_path, "w") as f:
    json.dump(obj, f)
print(json.dumps(obj))
