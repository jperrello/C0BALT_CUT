#!/usr/bin/env python3
import html, json, os, subprocess, sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8765"))

SECTIONS = [
    ("topic", "segment-topics, pick-segments",
     "Did this topic earn your interest on its own?"),
    ("hook", "pick-segments, bookend-trim",
     "Did the first 3 seconds grab you? Did it end clean, not mid-thought?"),
    ("title", "generate-title",
     "Would the title card stop a cold scroller? Still honest after watching?"),
    ("captions", "chunk-captions, burn-subtitles",
     "Readable, well-chunked, in sync?"),
    ("broll", "broll-pick, broll-composite",
     "Did cutaways match the story's tone? Right density and timing?"),
    ("music", "pick-mood, bg-music",
     "Does the song fit the theme? Sitting at the right level?"),
    ("pacing", "trim-filler, tighten-pace",
     "Any dead air, jarring cuts, or rushed moments?"),
]

UNBLOCK = """while tmux has-session -t %(s)s 2>/dev/null; do
  if tmux capture-pane -t %(s)s -p -S -20 2>/dev/null | grep -q "Yes, allow all edits during this session"; then
    tmux send-keys -t %(s)s "2" Enter
  fi
  sleep 8
done"""


def page():
    rows = []
    for key, owns, q in SECTIONS:
        rows.append(f"""<p><b>{key}</b> <small>({owns})</small><br>
{q}<br>
score <select name="s_{key}"><option></option><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option></select><br>
<textarea name="w_{key}" rows="2" cols="90" placeholder="why (this is the real signal)"></textarea></p>""")
    body = "\n".join(rows)
    return f"""<!doctype html><title>shorts review</title>
<h3>shorts review</h3>
<form method="post" action="/submit">
<p>video path<br><input name="video" size="100" placeholder="/Users/jperr/Documents/shorts/output/&lt;source&gt;/&lt;short&gt;.mp4"></p>
{body}
<p><b>overall</b><br>
verdict <select name="verdict"><option>rework</option><option>post</option><option>kill</option></select><br>
<textarea name="w_overall" rows="2" cols="90" placeholder="why"></textarea></p>
<p><input type="submit" value="submit + spawn fixer"></p>
</form>
Score 1-5, blank = no opinion. Submit spawns an autonomous claude tmux session
that fixes the scored problems on this video. Original is never overwritten."""


def record(form):
    out = {}
    for key, _, _ in SECTIONS:
        sec = {}
        score = form.get(f"s_{key}", [""])[0].strip()
        why = form.get(f"w_{key}", [""])[0].strip()
        if score:
            sec["score"] = int(score)
        if why:
            sec["why"] = why
        if sec:
            out[key] = sec
    overall = {"verdict": form.get("verdict", ["rework"])[0].strip()}
    if form.get("w_overall", [""])[0].strip():
        overall["why"] = form["w_overall"][0].strip()
    out["overall"] = overall
    return out


def mission(video, sections, ts):
    owns = "\n".join(f"- {k}: owned by {o}" for k, o, _ in SECTIONS)
    return f"""# Mission: fix this short per the user's scored feedback

You are an autonomous fixer session spawned by review.py in
{ROOT}. There is NO human in the loop.

## Hard operating rules (non-negotiable)
- The AskUserQuestion tool is PROHIBITED. Never ask the user anything,
  never wait for input, never end your turn with a question.
- Never stop to clarify. When something is ambiguous, pick the most
  reasonable interpretation, write the assumption into the report, and
  keep moving.
- If a step fails, try an alternative approach. Only after exhausting
  options do you record the failure in the report and move to the next fix.
- NEVER overwrite the original video. The fixed render saves next to the
  original as <stem>.fixed.mp4.
- Work until the fixed render exists and the report is written, then stop.

## Inputs
- Video: {video}
- Feedback (scores 1-5, lower is worse; the why text is the instruction):
```json
{json.dumps(sections, indent=2)}
```

## Section ownership
{owns}
- overall: verdict post / rework / kill

## Step 1: locate the work artifacts
Find the work/<id>/ dir and clip_NN that produced this video. Match the
output dir name against each work/<id>/ingest.json title, and the video
filename against clip_NN.title.txt slugs or *.lsmeta save records. If no
work dir survives, you can still fix title/captions/music/pacing by
operating on the video itself with ffmpeg plus a fresh whisper transcript;
note the degraded mode in the report.

## Step 2: plan the fixes
Fix every section scored 3 or below, and any section whose why text asks
for a change regardless of score. Read CLAUDE.md for the canonical stage
order, then re-run from the EARLIEST changed stage downstream; skills live
at .claude/skills/<name>/<name>.sh and shorts.sh shows how each is invoked
with work/<id>/clip_NN.* artifacts.

Per section:
- topic: an existing short cannot change its topic; fold the why into
  taste.md only. Exception: if the why explicitly asks for different in/out
  points, adjust the span cuts and re-render.
- hook: adjust the span start/end (bookend logic) so the opening words land
  the hook and the ending is clean, then re-render downstream.
- title: re-run generate-title with the why appended to its prompt context,
  then title-transition onward.
- captions: parameter-driven. Edit the relevant parameters (chunk length in
  chunk-captions, font size/position/timing in burn-subtitles) to satisfy
  the why, then re-run from chunk-captions or burn-subtitles onward.
- broll: re-run broll-pick treating the why as standing guidance, then
  broll-composite onward.
- music: re-run pick-mood and/or bg-music. A theme mismatch means a
  different mood folder; a level complaint means changing the bed volume
  parameter on the bg-music invocation.
- pacing: parameter-driven. Adjust trim-filler aggressiveness or the
  tighten-pace silence threshold per the why, then re-render downstream.

Parameter-driven stages have no prompt to steer, so YOU are the feedback
mechanism: prefer per-invocation parameter overrides for this render; only
change a repo default when the why states a clearly standing preference,
and say so in the report.

## Step 3: render and verify
Assemble the fixed chain in canonical order and save as
<original stem>.fixed.mp4 next to the original. Verify per CLAUDE.md:
1080x1920 full-bleed, title card in the first ~2.5s, CTA in the last ~4s,
audio at -14 LUFS with the bed under it.

## Step 4: compound the feedback into taste.md
Update {ROOT}/taste.md. Contract: one `## <key>` section per feedback key
(topic, hook, title, captions, broll, music, pacing, overall); bullets
only, max 5 per section; each bullet one imperative generalized
instruction derived from the why text, never invented; newest feedback
wins over contradicted older bullets. generate-title, pick-mood, and
pick-segments inject these sections into their prompts; broll-pick reads
## broll per its SKILL.md.

## Step 5: report and commit
Write feedback/missions/{ts}.report.md: what you fixed, parameters
changed (per-invocation vs repo default), assumptions made, anything you
could not fix and why. Commit and push any repo file changes (taste.md,
parameter defaults) with a clear message; never commit videos or
feedback/.
"""


def spawn(path, ts):
    if os.environ.get("DRY"):
        return "(dry: no session spawned)"
    session = f"shorts-fix-{ts}"
    bin = os.environ.get("CLAUDE_BIN", "claude")
    subprocess.run(["tmux", "new-session", "-d", "-s", session, "-c", ROOT,
                    "-e", "CLAUDECODE=", "-e", "NODE_OPTIONS="], check=True)
    subprocess.run(["tmux", "set-option", "-t", session, "remain-on-exit", "on"], check=True)
    subprocess.run(["tmux", "respawn-pane", "-k", "-t", session,
                    f"exec {bin} --dangerously-skip-permissions --append-system-prompt-file '{path}' "
                    f"'You are live. Execute the mission in your system prompt now, start to finish, without asking anything.'"],
                   check=True)
    subprocess.Popen(["bash", "-c", UNBLOCK % {"s": session}],
                     start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return session


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, code=200):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.reply(page())

    def do_POST(self):
        form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        video = form.get("video", [""])[0].strip()
        if not video or not os.path.exists(video):
            self.reply(f"video path not found: {html.escape(video)}<br><a href=/>back</a>", 400)
            return
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        sections = record(form)
        os.makedirs(os.path.join(ROOT, "feedback", "missions"), exist_ok=True)
        with open(os.path.join(ROOT, "feedback", "history.jsonl"), "a") as out:
            out.write(json.dumps({"video": video, "reviewed": ts, "sections": sections}) + "\n")
        path = os.path.join(ROOT, "feedback", "missions", f"{ts}.md")
        open(path, "w").write(mission(video, sections, ts))
        session = spawn(path, ts)
        self.reply(f"""spawned <b>{html.escape(session)}</b> on {html.escape(os.path.basename(video))}<br>
watch: <code>tmux attach -t {html.escape(session)}</code> (detach: ctrl-b d)<br>
mission: <code>{html.escape(path)}</code><br>
fixed render will land next to the original as .fixed.mp4<br>
<a href=/>review another</a>""")

    def log_message(self, fmt, *args):
        sys.stderr.write(fmt % args + "\n")


if __name__ == "__main__":
    print(f"shorts review: http://127.0.0.1:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
