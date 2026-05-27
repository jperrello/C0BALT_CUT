#!/usr/bin/env bash
set -e

CREW=~/.claude/skills/crew/crew.sh
NAME=ralph
PROMPT=ralph/RALPH_PROMPT.md

if ! bash "$CREW" list 2>/dev/null | awk '$2=="'"$NAME"'"{print $4}' | grep -q alive; then
    bash "$CREW" spawn local "$NAME" "$PWD"
    sleep 5
fi

while :; do
    echo "=== Pass starting $(date) ==="
    bash "$CREW" dispatch --timeout 3600 "$NAME" "$(cat "$PROMPT")"
    sleep 2
done
