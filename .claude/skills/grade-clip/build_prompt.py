import sys, json, re

# Build ONE prompt asking claude to rate the OPENING of a finished short on three
# 0-10 axes: hook<->payoff coherence, open-loop strength, cold-viewer context.
# Input: the title + the first ~10s of the clip-local transcript.
clip, transcript_path, title_path = sys.argv[1:4]

title = ""
try:
    title = open(title_path).read().strip()
except Exception:
    title = ""

words = []
try:
    tx = json.load(open(transcript_path))
    for w in tx.get("words", []):
        if float(w.get("t0", 0.0)) <= 10.0:
            words.append(str(w.get("w", "")))
except Exception:
    words = []
opening = " ".join(words).strip() or "(transcript unavailable)"

print(f"""You are grading the OPENING of a YouTube Short for cold-viewer retention.

TITLE: {title or "(none)"}

OPENING TRANSCRIPT (first ~10 seconds, no punctuation):
{opening}

Rate each axis 0-10 (10 = best):
- hook_payoff: does the opening promise/setup actually pay off the title's hook? Does what is said cohere with what the title claims?
- open_loop: does the opening open a curiosity loop a stranger wants resolved (a question, tension, or unresolved claim)?
- cold_context: can a stranger with ZERO context follow the first sentence — is the subject named, no dangling pronoun / dependent clause / mid-thought fragment?

Reply with ONLY a JSON object, no prose, no code fences:
{{"hook_payoff": <int 0-10>, "open_loop": <int 0-10>, "cold_context": <int 0-10>}}""")
