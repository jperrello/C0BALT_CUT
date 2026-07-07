import sys, os, json, glob, argparse

VERSION = 1

LEVERS = {
    "cuts.cuts_per_min": {"lever": "JUMP_CUT_SEG", "invert": True},
    "cuts.median_shot_sec": {"lever": "JUMP_CUT_SEG", "invert": False},
    "cuts.longest_static_gap": {"lever": "JUMP_CUT_MAX_GAP", "invert": False},
    "speech.words_per_min": {"lever": "SPEED", "invert": False},
    "speech.max_silence_sec": {"lever": "SPEED", "invert": False},
    "speech.speech_fraction": {"lever": "SPEED", "invert": False},
    "visual.cutaway_fraction": {"lever": "SWITCH_SPACING", "invert": True},
}

DIAGNOSTIC = [
    "duration_sec", "cuts.p90_shot_sec", "visual.face_fraction",
    "visual.cutaway_count", "captions.present_fraction", "audio.onsets_per_min",
    "audio.music_floor_db", "hook.first_cut_sec",
]


def get(doc, dotted):
    cur = doc
    for k in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    if isinstance(cur, bool):
        return None
    if isinstance(cur, (int, float)):
        return float(cur)
    return None


def robust(vals):
    vals = sorted(vals)
    med = vals[len(vals) // 2]
    mad = sorted(abs(v - med) for v in vals)[len(vals) // 2]
    sigma = 1.4826 * mad
    floor = abs(med) * 0.10
    return round(med, 3), round(max(sigma, floor, 1e-6), 3)


def distill(profiles):
    fields = {}
    for dotted in list(LEVERS) + DIAGNOSTIC:
        vals = [v for p in profiles if (v := get(p, dotted)) is not None]
        if len(vals) < 2:
            continue
        med, sigma = robust(vals)
        entry = {"median": med, "sigma": sigma, "n": len(vals)}
        if dotted in LEVERS:
            entry.update(LEVERS[dotted])
        else:
            entry["diagnostic"] = True
        fields[dotted] = entry
    return {
        "style_profile_version": VERSION,
        "n": len(profiles),
        "clips": [p.get("clip", "") for p in profiles],
        "fields": fields,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("refs")
    ap.add_argument("out")
    a = ap.parse_args()
    profiles = []
    for fp in sorted(glob.glob(os.path.join(a.refs, "profiles", "*.styleprofile.json"))):
        try:
            p = json.load(open(fp))
        except Exception:
            continue
        if p.get("style_profile_version") != VERSION or p.get("error"):
            continue
        profiles.append(p)
    doc = distill(profiles)
    json.dump(doc, open(a.out, "w"), indent=2)
    print(json.dumps({"out": a.out, "n": doc["n"], "fields": len(doc["fields"])}))


if __name__ == "__main__":
    main()
