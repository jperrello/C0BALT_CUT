---
name: save-local
description: Move a rendered short into ./output/<source-video-name>/. Auto-creates the per-source folder. Use as the final step so all shorts from one source video land in one browseable folder.
---

# save-local

Final-stage delivery. Local filesystem only (no Drive, no cloud).

## Inputs
- `input`: rendered short path
- `source`: original source video path (used to derive folder name)
- `name` (optional): destination filename, defaults to `<input basename>`

## Output
Path to the saved file: `<OUTPUT_DIR>/<source-stem>/<name>`. Returns the path.

## How
1. Read `OUTPUT_DIR` from `.env` (default `./output`).
2. Derive folder from `Path(source).stem`.
3. `mkdir -p <OUTPUT_DIR>/<stem>`.
4. Copy (not move — preserve the render in its working dir) the file in.
5. Print the absolute destination path so the user can open it.

## Status
Implemented — `save-local.sh`.
