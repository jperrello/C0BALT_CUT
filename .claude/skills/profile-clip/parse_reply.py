import sys, json

ENUMS = {
    "broll_mode": {"literal", "archival", "abstract", "none"},
    "caption_style": {"karaoke_accent", "plain_line", "block", "none"},
    "production_class": {"single_interview", "multicam", "staged", "compilation"},
    "hook_device": {"claim", "question", "action", "face_react"},
}


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


def merge(profile, reply):
    doc = extract(reply or "")
    if not isinstance(doc, dict):
        profile.setdefault("vision", {})["confidence"] = 0.0
        return profile
    vis = profile.setdefault("vision", {})
    for k, allowed in ENUMS.items():
        v = doc.get(k)
        if isinstance(v, str) and v in allowed:
            vis[k] = v
    try:
        vis["confidence"] = max(0.0, min(1.0, float(doc.get("confidence", 0.5))))
    except Exception:
        vis["confidence"] = 0.5
    if isinstance(doc.get("opens_on_face"), bool) and "opens_on_face" not in profile.get("visual", {}):
        profile.setdefault("visual", {})["opens_on_face"] = doc["opens_on_face"]
    cf = doc.get("cutaway_fraction")
    if isinstance(cf, (int, float)) and "cutaway_fraction" not in profile.get("visual", {}):
        profile.setdefault("visual", {})["cutaway_fraction"] = max(0.0, min(1.0, float(cf)))
    profile.setdefault("meta", {})["needs_vision"] = []
    return profile


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("usage: parse_reply.py <profile.json> <reply.txt>\n")
        sys.exit(2)
    profile = json.load(open(sys.argv[1]))
    try:
        reply = open(sys.argv[2]).read()
    except Exception:
        reply = ""
    json.dump(merge(profile, reply), open(sys.argv[1], "w"), indent=2)
    print(json.dumps({"vision": profile.get("vision", {})}))


if __name__ == "__main__":
    main()
