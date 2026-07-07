#!/usr/bin/env bash
# profile-clip: the sidecar-free style analyzer — reduce ANY finished .mp4
# (ours or a downloaded exemplar) into a Style Profile JSON using ONLY pixels
# + audio, never our internal plans. Deterministic tier (ffprobe / scene-detect
# / silencedetect / RMS / MediaPipe / caption-band edges) fills every
# quantitative field; ONE optional Claude vision call (contact sheet) fills the
# enumerated judgment fields (broll_mode, caption_style, production_class,
# hook_device) when PROFILE_VISION=1. Non-fatal: any failure still writes a
# best-effort profile (or an error stub) and exits 0. Idempotent via .ppmeta.
#
#   profile-clip.sh <clip.mp4> <out.styleprofile.json> [--no-vision] [--pane <p>]
set -uo pipefail

source "$(cd "$(dirname "$0")/../_lib" && pwd)/pane.sh"
parse_pane_flag "$@"
set -- "${SHORTS_REST[@]+"${SHORTS_REST[@]}"}"

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }

clip="${1:-}"; out="${2:-}"
vision="${PROFILE_VISION:-1}"
[[ "${3:-}" == "--no-vision" ]] && vision=0
if [[ -z "$clip" || -z "$out" ]]; then
  echo "usage: profile-clip.sh <clip.mp4> <out.json> [--no-vision] [--pane <p>]" >&2
  exit 2
fi
if [[ ! -f "$clip" ]]; then
  echo "profile-clip: clip not found: $clip — skipping" >&2
  exit 0
fi

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
meta="${out%.json}.ppmeta"
sig="$(mtime "$clip")|v=$vision|s=${PROFILE_SCENE:-0.3}|n=${PROFILE_SAMPLES:-16}|v1"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "profile-clip: cache hit at $out" >&2
  exit 0
fi

if ! python3 "$here/profile.py" "$clip" "$out" >&2; then
  echo "profile-clip: deterministic tier failed — non-fatal" >&2
  [[ -f "$out" ]] || printf '{"style_profile_version":1,"clip":"%s","error":"profile failed"}' "$clip" > "$out"
  printf '%s' "$sig" > "$meta"
  exit 0
fi

# ---- vision escalation: one contact-sheet call for the judgment fields -----
needs="$(python3 -c 'import json,sys; print(",".join((json.load(open(sys.argv[1])).get("meta") or {}).get("needs_vision") or []))' "$out" 2>/dev/null)"
if [[ "$vision" != "0" && -n "$needs" ]]; then
  td="$(mktemp -d)"
  sheetjson="$(python3 "$here/../director-pass/frames.py" "$clip" "$td" --n "${PROFILE_FRAMES:-12}" 2>/dev/null)"
  sheet="$(printf '%s' "$sheetjson" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("sheet",""))
except Exception: print("")' 2>/dev/null)"
  if [[ -n "$sheet" && -f "$sheet" ]]; then
    python3 "$here/build_prompt.py" "$sheet" "$out" --needs "$needs" > "$td/prompt.txt" 2>/dev/null
    if [[ -s "$td/prompt.txt" ]] && run_claude_step profile-clip-vision "$td/prompt.txt" "$td/reply.txt" 2>"$td/err"; then
      python3 "$here/parse_reply.py" "$out" "$td/reply.txt" >&2 \
        || echo "profile-clip: vision merge failed — deterministic profile ships" >&2
    else
      echo "profile-clip: vision call unavailable — deterministic profile ships" >&2
    fi
  else
    echo "profile-clip: contact sheet failed — deterministic profile ships" >&2
  fi
  rm -rf "$td" 2>/dev/null
fi

printf '%s' "$sig" > "$meta"
echo "profile-clip: wrote $out" >&2
exit 0
