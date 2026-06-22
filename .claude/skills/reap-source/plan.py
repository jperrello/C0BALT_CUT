import os, sys

# Print every reclaimable HEAVY artifact in a work/<id> dir, one path per line.
# Reclaimable = the full podcast download + per-stage clip intermediates + the
# b-roll cutaway cache. NEVER any .json/.txt/.path/*meta — those are the cheap
# "memory" the ledger keeps (transcript/ingest/topics/segments/grade/broll_plan).
d = sys.argv[1]
exts = (".mp4", ".mov", ".wav", ".m4a", ".webm", ".mkv")
out = []

src = os.path.join(d, "source.mp4")
if os.path.isfile(src):
    out.append(src)

for f in sorted(os.listdir(d)):
    p = os.path.join(d, f)
    if os.path.isfile(p) and f.startswith("clip_") and f.endswith(exts):
        out.append(p)

broll = os.path.join(d, "broll")
if os.path.isdir(broll):
    for r, _, files in os.walk(broll):
        for f in files:
            out.append(os.path.join(r, f))

print("\n".join(out))
