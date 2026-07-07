#!/usr/bin/env bash
# style-corpus: the offline LEARN phase of the style-replication loop.
#   learn <url|file>...   yt-dlp each Group C exemplar into work/_style/<id>/
#                         (gitignored), profile it sidecar-free via profile-clip
#                         (vision ON), store the small JSON profile in
#                         references/profiles/<id>.styleprofile.json (checked in)
#   distill               aggregate all profiles -> references/targets.json
#                         (robust median/MAD per levered field)
#   show                  print targets.json
# Non-fatal per exemplar: a failed download/profile skips that URL.
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }

refs="${STYLE_REFS:-$root/references}"
mkdir -p "$refs/profiles" "$root/work/_style"

cmd="${1:-show}"; shift || true

sid() { printf '%s' "$1" | shasum | cut -c1-10; }

learn() {
  local src id media
  for src in "$@"; do
    id="$(sid "$src")"
    media="$root/work/_style/$id/exemplar.mp4"
    mkdir -p "$root/work/_style/$id"
    if [[ -f "$src" ]]; then
      media="$src"
    elif [[ ! -f "$media" ]]; then
      echo "style-corpus: downloading $src" >&2
      if ! yt-dlp -q -f "bv*[height<=1920]+ba/b" --merge-output-format mp4 \
           -o "$media" "$src" 2>&2; then
        echo "style-corpus: download failed for $src — skipping" >&2
        continue
      fi
      printf '%s\n' "$src" > "$root/work/_style/$id/url.txt"
    fi
    bash "$here/../profile-clip/profile-clip.sh" "$media" \
      "$refs/profiles/$id.styleprofile.json" ${SHORTS_PANE:+--pane "$SHORTS_PANE"} || true
    python3 - "$refs/profiles/$id.styleprofile.json" "$src" <<'PY' 2>/dev/null || true
import json, sys
p = json.load(open(sys.argv[1]))
p.setdefault("meta", {})["source_url"] = sys.argv[2]
json.dump(p, open(sys.argv[1], "w"), indent=2)
PY
  done
}

case "$cmd" in
  learn)
    [[ $# -eq 0 ]] && { echo "usage: style-corpus.sh learn <url|file>..." >&2; exit 2; }
    learn "$@"
    python3 "$here/distill.py" "$refs" "$refs/targets.json" >&2 || true
    ;;
  distill)
    python3 "$here/distill.py" "$refs" "$refs/targets.json" >&2 || true
    ;;
  show)
    cat "$refs/targets.json" 2>/dev/null || echo "style-corpus: no targets yet — run learn/distill" >&2
    ;;
  *)
    echo "usage: style-corpus.sh learn|distill|show" >&2
    exit 2
    ;;
esac
exit 0
