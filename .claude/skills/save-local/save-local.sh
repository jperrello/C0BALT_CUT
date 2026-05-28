#!/usr/bin/env bash
# save-local: copy a rendered short into <OUTPUT_DIR>/<subdir>/
# subdir defaults to the source stem when not given.
set -euo pipefail

input="${1:-}"
source="${2:-}"
name="${3:-}"
subdir="${4:-}"

if [[ -z "$input" || -z "$source" ]]; then
  echo "usage: save-local.sh <input> <source> [name] [subdir]" >&2
  exit 2
fi
if [[ ! -f "$input" ]]; then
  echo "save-local: input not found: $input" >&2
  exit 2
fi

here="$(cd "$(dirname "$0")" && pwd)"
root="$here/../../.."
if [[ -f "$root/.env" ]]; then
  set -a; . "$root/.env"; set +a
fi
outdir="${OUTPUT_DIR:-./output}"

stem="$subdir"
if [[ -z "$stem" ]]; then
  stem="$(basename "$source")"
  stem="${stem%.*}"
fi
[[ -z "$name" ]] && name="$(basename "$input")"

dest_dir="$outdir/$stem"
mkdir -p "$dest_dir"
dest="$dest_dir/$name"
cp "$input" "$dest"

abs="$(cd "$(dirname "$dest")" && pwd)/$(basename "$dest")"
echo "save-local: saved -> $abs" >&2
echo "$abs"
