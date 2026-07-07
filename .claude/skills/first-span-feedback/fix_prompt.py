import os, json, argparse


def loadjson(p):
    if not p or not os.path.isfile(p):
        return None
    try:
        return json.load(open(p))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("verdict")
    ap.add_argument("--grade", default="")
    ap.add_argument("--transcript", default="")
    a = ap.parse_args()

    v = loadjson(a.verdict) or {}
    dclass = str(v.get("defect_class", "other") or "other")
    signal = v.get("signal")
    where = str(v.get("where", "") or "").strip()
    rationale = str(v.get("rationale", "") or "").strip()

    grade = loadjson(a.grade) or {}
    gline = "proxy grade %s/%s; hard_caps=%s; signals=%s" % (
        grade.get("grade"), grade.get("tier"),
        ",".join(grade.get("hard_caps") or []) or "none",
        json.dumps(grade.get("signals") or {}))

    print(f"""You are fixing a SYSTEMIC defect in the C0BALT_CUT shorts pipeline. A first-span reviewer watched span 0 (the first short from this source) and flagged a fault that WILL recur on every later span and every future run, because they all render on the SAME skill code.

DEFECT
  class:     {dclass}
  signal:    {signal}
  where:     {where or "(reviewer did not localize — trace it from the symptom)"}
  rationale: {rationale}

GRADE / SIGNALS (grade-clip, the swipe-gate proxy):
  {gline}

YOUR TASK
- Find and fix the ROOT CAUSE in the codebase — a skill's logic under `.claude/skills/<name>/`, a shared lib, an entrypoint, or a default. Edit any repo file needed.
- Do NOT patch this one clip, and do NOT touch anything under `work/` or `output/` (those are re-rendered media, gitignored). A per-clip band-aid is a FAILED fix.
- Keep the change minimal and surgical: correct the one systemic behavior the reviewer named; do not refactor unrelated code or sweep in the operator's pre-existing edits.
- Honor CLAUDE.md conventions (single-word names, python3, no docstrings, early returns, no hardcoded paths).

After you edit, the loop will re-render span 0 and re-grade it. The fix is KEPT only if the new grade does not regress AND the flagged signal clears AND a re-review finds the defect gone — so make a real root-cause correction, not a cosmetic one.

Make the edits now. Reply with a one-line summary of what you changed and why it fixes the root cause.""")


if __name__ == "__main__":
    main()
