import sys, os, json, re, argparse

APPLY = {"tail_trim", "music_down"}
KINDS = {"tail_dead", "cold_open", "broll_wrong", "wrong_person",
         "caption_mistime", "music_loud", "flat_hook", "other"}
SEV = {"high", "med", "low"}


def extract(text):
    # first balanced {...} object in the reply (tolerates fences / prose)
    s = text.find("{")
    if s < 0:
        return None
    depth = 0
    instr = False
    esc = False
    for i in range(s, len(text)):
        ch = text[i]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[s:i + 1])
                except Exception:
                    return None
    return None


def clampwhere(where, dur):
    if not isinstance(where, list) or len(where) != 2:
        return None
    try:
        a = max(0.0, min(dur, float(where[0])))
        b = max(0.0, min(dur, float(where[1])))
    except Exception:
        return None
    if b < a:
        a, b = b, a
    return [round(a, 2), round(b, 2)]


def normalize(reply, dur, mode, vol, mindur):
    doc = extract(reply) or {}
    issues_in = doc.get("issues") if isinstance(doc.get("issues"), list) else []
    summary = str(doc.get("summary", "")).strip()[:240]

    ops = []
    for it in issues_in:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind", "other")).strip().lower()
        if kind not in KINDS:
            kind = "other"
        sev = str(it.get("severity", "med")).strip().lower()
        if sev not in SEV:
            sev = "med"
        where = clampwhere(it.get("where"), dur)
        detail = str(it.get("detail", "")).strip()[:300]
        op = str(it.get("op", "surface")).strip().lower()
        params = it.get("params") if isinstance(it.get("params"), dict) else {}

        rec = {"op": "surface", "kind": kind, "severity": sev,
               "where": where, "detail": detail, "rerun_recommended": False}

        if op == "tail_trim":
            t1 = params.get("t1", (where or [0, 0])[1])
            try:
                t1 = round(float(t1), 2)
            except Exception:
                t1 = None
            # must cut something real off the end and leave a viable clip
            if t1 is not None and mindur <= t1 <= dur - 0.25:
                rec["op"] = "tail_trim"
                rec["t1"] = t1
            else:
                rec["detail"] = (detail + " | tail_trim out of range (t1=%s) -> surfaced" % t1).strip(" |")
        elif op == "music_down":
            if mode == "curative":
                rec["detail"] = (detail + " | music_down needs the pre-mix clip (in-chain only) -> surfaced").strip(" |")
                rec["rerun_recommended"] = True
            else:
                try:
                    v = float(params.get("volume"))
                except Exception:
                    v = None
                cur = float(vol)
                if v is not None and 0.03 <= v <= cur - 0.01:
                    rec["op"] = "music_down"
                    rec["volume"] = round(v, 3)
                else:
                    rec["detail"] = (detail + " | music_down volume invalid (%s) -> surfaced" % v).strip(" |")
        elif op == "surface":
            pass
        else:
            rec["detail"] = (detail + " | unsupported op '%s' -> surfaced" % op).strip(" |")

        # cold-open / structural classes a standalone pass can't repair in place
        if rec["op"] == "surface" and kind in ("cold_open", "wrong_person", "caption_mistime", "broll_wrong"):
            rec["rerun_recommended"] = True
        ops.append(rec)

    verdict = str(doc.get("verdict", "")).strip().lower()
    actionable = any(o["op"] in APPLY for o in ops)
    if verdict not in ("ship", "revise"):
        verdict = "revise" if ops else "ship"
    if not ops:
        verdict = "ship"

    return {"verdict": verdict, "summary": summary, "ops": ops,
            "actionable": actionable}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")

    n = sub.add_parser("normalize")
    n.add_argument("reply")
    n.add_argument("dur", type=float)
    n.add_argument("out")
    n.add_argument("--mode", default="curative")
    n.add_argument("--vol", default="0.17")
    n.add_argument("--mindur", type=float, default=15.0)

    o = sub.add_parser("ops")
    o.add_argument("review")

    a = ap.parse_args()

    if a.cmd == "normalize":
        try:
            reply = open(a.reply).read()
        except Exception:
            reply = ""
        doc = normalize(reply, a.dur, a.mode, a.vol, a.mindur)
        json.dump(doc, open(a.out, "w"), indent=2)
        print(doc["verdict"])
        return

    if a.cmd == "ops":
        try:
            doc = json.load(open(a.review))
        except Exception:
            return
        for o in doc.get("ops", []):
            if o.get("op") == "tail_trim":
                print("tail_trim\t%s\t" % o.get("t1", ""))
            elif o.get("op") == "music_down":
                print("music_down\t\t%s" % o.get("volume", ""))
        return

    ap.error("no command")


if __name__ == "__main__":
    main()
