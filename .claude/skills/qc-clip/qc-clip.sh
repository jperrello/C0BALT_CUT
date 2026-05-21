#!/usr/bin/env bash
# qc-clip: ffprobe sanity check -> verdict JSON
set -euo pipefail

input="${1:-}"
dmin="${2:-15}"
dmax="${3:-90}"
min_kb="${4:-100}"

if [[ -z "$input" ]]; then
  echo "usage: qc-clip.sh <input> [min_duration=15] [max_duration=90] [min_size_kb=100]" >&2
  exit 2
fi
if [[ ! -f "$input" ]]; then
  echo "qc-clip: input not found: $input" >&2
  exit 2
fi

probe="$(ffprobe -v error -show_entries format=duration,size -of json "$input")"

python3 - "$input" "$probe" "$dmin" "$dmax" "$min_kb" <<'PY'
import json, sys
input, probe, dmin, dmax, min_kb = sys.argv[1:6]
dmin, dmax, min_kb = float(dmin), float(dmax), float(min_kb)

fmt = json.loads(probe).get("format", {})
dur = float(fmt.get("duration", 0) or 0)
size_kb = float(fmt.get("size", 0) or 0) / 1024.0

reason = ""
if dur < dmin:
    reason = f"duration {dur:.1f}s below min {dmin:.0f}s"
elif dur > dmax:
    reason = f"duration {dur:.1f}s above max {dmax:.0f}s"
elif size_kb < min_kb:
    reason = f"size {size_kb:.0f}KB below min {min_kb:.0f}KB"

print(json.dumps({
    "pass": reason == "",
    "duration": round(dur, 1),
    "size_kb": round(size_kb),
    "reason": reason,
}, indent=2))
PY
