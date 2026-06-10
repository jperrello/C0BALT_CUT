#!/usr/bin/env python3
import json, os, re, sys


def front(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def field(body, name):
    m = re.search(rf"^{name}[^:\n]*:\s*(.*)$", body, re.M)
    if not m:
        return ""
    out = [m.group(1).strip()]
    for line in body[m.end():].splitlines()[1:]:
        bare = line.strip()
        if not bare:
            break
        if re.match(r"^(score|why|verdict|##|<!--)", bare):
            break
        out.append(bare)
    return " ".join(x for x in out if x).strip()


def sections(text):
    out = {}
    for m in re.finditer(r"^## (\w+)\n(.*?)(?=^## |\Z)", text, re.S | re.M):
        body = m.group(2)
        sec = {}
        score = field(body, "score")
        if score and score[0].isdigit():
            sec["score"] = int(score[0])
        if field(body, "why"):
            sec["why"] = field(body, "why")
        if field(body, "verdict"):
            sec["verdict"] = field(body, "verdict")
        if sec:
            out[m.group(1)] = sec
    return out


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else "./output"
    rows = []
    skipped = 0
    for dirpath, _, files in os.walk(root):
        for f in sorted(files):
            if not f.endswith(".feedback.md"):
                continue
            text = open(os.path.join(dirpath, f)).read()
            head = front(text)
            if not head.get("reviewed"):
                skipped += 1
                continue
            head["sections"] = sections(text)
            head["form"] = os.path.join(dirpath, f)
            rows.append(head)
    os.makedirs("feedback", exist_ok=True)
    with open("feedback/history.jsonl", "w") as out:
        for r in sorted(rows, key=lambda r: (r.get("reviewed", ""), r.get("short", ""))):
            out.write(json.dumps(r) + "\n")
    print(f"{len(rows)} reviewed forms -> feedback/history.jsonl ({skipped} unreviewed skipped)")
