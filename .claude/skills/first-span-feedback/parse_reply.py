import sys, json


# first balanced {...} object in the reply (tolerates fences / prose around it).
def extract(text):
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


# Fail-safe verdict: any parse failure -> {"defect": false} (ship unchanged).
def verdict(text):
    doc = extract(text or "")
    if not isinstance(doc, dict) or "defect" not in doc:
        return {"defect": False}
    d = bool(doc.get("defect"))
    if not d:
        return {"defect": False}
    sig = doc.get("signal")
    if sig in (None, "", "null", "None"):
        sig = None
    else:
        sig = str(sig).strip()[:60]
    return {
        "defect": True,
        "defect_class": str(doc.get("defect_class", "") or "other").strip()[:60],
        "signal": sig,
        "where": str(doc.get("where", "") or "").strip()[:160],
        "rationale": str(doc.get("rationale", "") or "").strip()[:400],
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"defect": False}))
        return
    try:
        text = open(sys.argv[1]).read()
    except Exception:
        text = ""
    print(json.dumps(verdict(text)))


if __name__ == "__main__":
    main()
