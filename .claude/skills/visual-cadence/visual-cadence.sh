#!/usr/bin/env bash
# visual-cadence: measure the longest stretch of a rendered clip with NO visual
# change (hard cut / reframe / b-roll cutaway), via ffmpeg scene detection.
# Emits a JSON verdict and a non-fatal WARN when the max static gap exceeds
# MAX_STATIC_GAP. DIAGNOSTIC ONLY — it never alters or rejects the clip. The
# union-of-all-visual-changes counterpart to the per-skill cut planners
# (jump-cut/zoom-punch/b-roll), and the keystone signal for the "12 seconds
# without a pattern interrupt" retention leak. Deterministic — no Claude.
# VISUAL_CADENCE=0 skips.
set -uo pipefail

input="${1:-}"
out="${2:-}"
max_gap="${3:-${MAX_STATIC_GAP:-5.0}}"
scene="${VCAD_SCENE:-0.3}"

if [[ -z "$input" ]]; then
  echo "usage: visual-cadence.sh <clip.mp4> [out.json] [max_gap=5.0]" >&2
  exit 2
fi
[[ -f "$input" ]] || { echo "visual-cadence: input not found: $input" >&2; exit 2; }
[[ -n "$out" ]] || out="${input%.*}.cadence.json"

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
sig="$(mtime "$input")|$max_gap|$scene|${VISUAL_CADENCE:-1}|v1"
meta="$out.vcadmeta"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "visual-cadence: cache hit at $out" >&2
  cat "$out"; exit 0
fi
mkdir -p "$(dirname "$out")"

emit() { printf '%s' "$1" > "$out"; printf '%s' "$sig" > "$meta"; cat "$out"; }

if [[ "${VISUAL_CADENCE:-1}" == "0" ]]; then
  emit '{"pass":true,"skipped":true,"reason":"disabled via VISUAL_CADENCE=0"}'; exit 0
fi

dur="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$input" 2>/dev/null)"
if [[ -z "$dur" ]] || ! python3 -c "import sys; sys.exit(0 if float('$dur')>0 else 1)" 2>/dev/null; then
  emit '{"pass":true,"reason":"could not read duration"}'; exit 0
fi

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# showinfo logs one line per SELECTED frame (scene score > threshold) -> pts_time
ffmpeg -hide_banner -nostats -i "$input" \
  -vf "select='gt(scene,${scene})',showinfo" -an -f null - 2>"$tmp/si.log" || true

verdict="$(python3 - "$tmp/si.log" "$dur" "$max_gap" "$scene" <<'PY'
import json, re, sys
log, dur, max_gap, scene = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
times = []
try:
    for line in open(log, errors="ignore"):
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
            if 0.0 <= t <= dur:
                times.append(round(t, 3))
except FileNotFoundError:
    pass
times = sorted(set(times))
bounds = [0.0] + times + [dur]
gap, ga, gb = 0.0, 0.0, dur
for a, b in zip(bounds, bounds[1:]):
    if b - a > gap:
        gap, ga, gb = b - a, a, b
print(json.dumps({
    "pass": gap <= max_gap,
    "duration": round(dur, 2),
    "threshold": max_gap,
    "scene": scene,
    "n_changes": len(times),
    "max_gap": round(gap, 2),
    "gap_window": [round(ga, 2), round(gb, 2)],
    "changes": times,
}))
PY
)"

emit "$verdict"
ok="$(printf '%s' "$verdict" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pass"])' 2>/dev/null || echo True)"
if [[ "$ok" != "True" ]]; then
  g="$(printf '%s' "$verdict" | python3 -c 'import json,sys
d=json.load(sys.stdin)
print(str(d["max_gap"])+"s @ "+str(d["gap_window"]))' 2>/dev/null || true)"
  echo "visual-cadence: WARN static gap ${g} exceeds ${max_gap}s — $input" >&2
fi
exit 0
