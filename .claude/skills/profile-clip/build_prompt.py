import sys, json, argparse

FIELDS = {
    "broll_mode": 'one of "literal" | "archival" | "abstract" | "none" — the dominant cutaway character',
    "caption_style": 'one of "karaoke_accent" | "plain_line" | "block" | "none"',
    "production_class": 'one of "single_interview" | "multicam" | "staged" | "compilation" — how the footage was PRODUCED (we cannot change this; report honestly)',
    "hook_device": 'one of "claim" | "question" | "action" | "face_react" — what carries the first ~2s',
    "opens_on_face": "true iff a human face is the subject of the first frame",
    "cutaway_fraction": "0-1: fraction of the frames NOT on the main talking head",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("profile")
    ap.add_argument("--needs", default="")
    a = ap.parse_args()
    prof = json.load(open(a.profile))
    needs = [n for n in a.needs.split(",") if n and n in FIELDS]
    if not needs:
        needs = ["broll_mode", "caption_style", "production_class", "hook_device"]
    asks = "\n".join('  "%s": %s' % (n, FIELDS[n]) for n in needs)
    print(f"""You are profiling the EDITING STYLE of a finished vertical short. Read the labelled contact sheet image at this absolute path (frames sampled evenly across the whole clip, each labelled t=…s):

{a.sheet}

Deterministic measurements already made (for context; do not restate):
{json.dumps({k: prof.get(k) for k in ("duration_sec", "cuts", "visual", "captions")}, indent=2)}

Judge ONLY the following fields from what you SEE and reply with ONE JSON object containing exactly these keys plus "confidence" (0-1) and nothing else:
{{
{asks},
  "confidence": 0.0
}}""")


if __name__ == "__main__":
    main()
