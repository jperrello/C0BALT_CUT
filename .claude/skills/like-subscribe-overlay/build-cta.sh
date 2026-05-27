#!/usr/bin/env bash
# build-cta.sh — render cta.html via Playwright into a transparent ProRes 4444
# .mov asset. Run this once (or whenever cta.html changes); the resulting
# assets/cta.mov is what like-subscribe-overlay.sh composites onto each clip.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"

fps="${1:-30}"
dur="${2:-3.0}"

if [[ ! -d node_modules/playwright ]]; then
  echo "build-cta: installing playwright (one-time)..." >&2
  npm i --silent --no-fund --no-audit playwright >&2
fi
# probe playwright for the chromium version it expects; install if missing.
if ! node -e "process.exit(require('playwright').chromium.executablePath() && require('fs').existsSync(require('playwright').chromium.executablePath()) ? 0 : 1)" 2>/dev/null; then
  echo "build-cta: installing chromium binary..." >&2
  npx playwright install chromium >&2
fi

frames="$(mktemp -d)"
trap 'rm -rf "$frames"' EXIT

node build-cta.js "$frames" "$fps" "$dur"

mkdir -p assets
ffmpeg -y -hide_banner -loglevel error \
  -framerate "$fps" -i "$frames/frame_%04d.png" \
  -c:v prores_ks -pix_fmt yuva444p10le -profile:v 4444 \
  -an "assets/cta.mov"

echo "build-cta: wrote $here/assets/cta.mov ($(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 assets/cta.mov)s)" >&2
