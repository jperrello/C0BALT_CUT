#!/usr/bin/env bash
# name-short: title text file -> kebab-case .mp4 filename
set -euo pipefail

title_file="${1:-}"
out_file="${2:-}"

if [[ -z "$title_file" ]]; then
  echo "usage: name-short.sh <title_file> [out_file]" >&2
  exit 2
fi
if [[ ! -f "$title_file" ]]; then
  echo "name-short: title file not found: $title_file" >&2
  exit 2
fi

slug="$(python3 - "$title_file" <<'PY'
import re, sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore").strip()
t = t.lower()
t = re.sub(r"[^a-z0-9]+", "-", t)
t = re.sub(r"-+", "-", t).strip("-")
if not t:
    t = "short"
print(t[:80])
PY
)"

name="$slug.mp4"
echo "$name"
if [[ -n "$out_file" ]]; then
  printf '%s\n' "$name" > "$out_file"
fi
