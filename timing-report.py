#!/usr/bin/env python3
# Reducer for the pipeline timing instrument (_lib/timing.sh).
#
# Reads work/<id>/run_timing.jsonl (one JSON record per line, appended live by
# `timed` + pane.sh's claude sub-record) plus the run's *.grade.json and
# *.fail* markers, and folds them into:
#   work/<id>/run_timing.json   machine report (total, sec_per_short, split,
#                               per-lane timeline, top_steps, guardrail)
#   output/<slug>/_timing.html  human report (per the mockup)
#
# Non-fatal by contract: any error logs to stderr and exits 0. A partial JSONL
# (crashed mid-run) still renders a partial report.
#
# usage:
#   timing-report.py <run_timing.jsonl> [work_dir] [out_html]
#     work_dir defaults to the dirname of the jsonl (where grade/fail markers live)
#     out_html optional; when given, the HTML report is written there
#
# The split:
#   claude  = sum of the measured pane sub-records (label ending "/claude")
#   ffmpeg  = sum of top-level skill spans tagged kind:"ffmpeg"
#   io      = total wrapped wall-clock of top-level spans MINUS claude MINUS ffmpeg

import json
import os
import re
import sys


def log(msg):
    sys.stderr.write("timing-report: %s\n" % msg)


def load_records(path):
    recs = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                # a half-written final line on a crashed run — skip it
                continue
    return recs


def dur(r):
    try:
        d = float(r.get("t1", 0)) - float(r.get("t0", 0))
        return d if d > 0 else 0.0
    except Exception:
        return 0.0


def is_sub(r):
    return str(r.get("label", "")).endswith("/claude")


def fmt_clock(sec):
    sec = int(round(sec))
    m, s = divmod(sec, 60)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


def collect_guardrail(work_dir):
    grades = []
    tier_mix = {}
    fail_count = 0
    try:
        for name in os.listdir(work_dir):
            full = os.path.join(work_dir, name)
            if name.endswith(".grade.json"):
                try:
                    g = json.load(open(full))
                    if isinstance(g.get("grade"), (int, float)):
                        grades.append(float(g["grade"]))
                    t = g.get("tier")
                    if t:
                        tier_mix[t] = tier_mix.get(t, 0) + 1
                except Exception:
                    continue
            elif ".fail" in name:
                # clip_NN.fail / .fail.captions / .fail.completion
                fail_count += 1
    except Exception as e:
        log("guardrail scan failed: %s" % e)
    mean_grade = round(sum(grades) / len(grades), 1) if grades else None
    return {
        "mean_grade": mean_grade,
        "tier_mix": tier_mix,
        "fail_count": fail_count,
    }


def build_report(recs, work_dir):
    tops = [r for r in recs if not is_sub(r)]
    subs = [r for r in recs if is_sub(r)]

    t_all = [float(r["t0"]) for r in recs if "t0" in r] + [
        float(r["t1"]) for r in recs if "t1" in r
    ]
    total = (max(t_all) - min(t_all)) if t_all else 0.0

    claude_sec = sum(dur(r) for r in subs)
    ffmpeg_sec = sum(dur(r) for r in tops if r.get("kind") == "ffmpeg")
    top_wrapped = sum(dur(r) for r in tops)
    io_sec = top_wrapped - claude_sec - ffmpeg_sec
    if io_sec < 0:
        io_sec = 0.0

    # per-lane timeline: group top-level spans by lane, then by span
    lanes = {}
    for r in tops:
        lane = r.get("lane")
        if lane is None:
            lane = 0
        lanes.setdefault(lane, []).append(r)
    lane_out = []
    for lane in sorted(lanes):
        spans = {}
        for r in lanes[lane]:
            sp = r.get("span")
            spans.setdefault(sp, []).append(r)
        span_out = []
        for sp in sorted(spans, key=lambda x: (x is None, x)):
            steps = sorted(spans[sp], key=lambda r: float(r.get("t0", 0)))
            phase = steps[0].get("phase") if steps else None
            span_out.append(
                {
                    "span": sp,
                    "phase": phase,
                    "t0": min(float(r["t0"]) for r in steps),
                    "t1": max(float(r["t1"]) for r in steps),
                    "steps": [
                        {
                            "label": r.get("label"),
                            "kind": r.get("kind"),
                            "t0": float(r.get("t0", 0)),
                            "t1": float(r.get("t1", 0)),
                            "sec": round(dur(r), 2),
                            "exit": r.get("exit", 0),
                        }
                        for r in steps
                    ],
                }
            )
        lane_out.append({"lane": lane, "spans": span_out})

    # top_steps: aggregate by label across all top-level spans. A label's
    # claude sub-record (if any) is reported as its own row too.
    agg = {}
    for r in tops + subs:
        lbl = r.get("label")
        if lbl not in agg:
            agg[lbl] = {
                "label": lbl,
                "kind": r.get("kind"),
                "total_sec": 0.0,
                "calls": 0,
            }
        agg[lbl]["total_sec"] += dur(r)
        agg[lbl]["calls"] += 1
    top_steps = sorted(
        ({**v, "total_sec": round(v["total_sec"], 2)} for v in agg.values()),
        key=lambda x: x["total_sec"],
        reverse=True,
    )[:12]

    guardrail = collect_guardrail(work_dir)
    delivered = guardrail["tier_mix"].get("GOLD", 0) + guardrail["tier_mix"].get(
        "FIXABLE", 0
    ) + guardrail["tier_mix"].get("DROSS", 0)
    # delivered shorts: count grade.json files (one per saved short)
    if delivered == 0:
        delivered = sum(guardrail["tier_mix"].values())
    sec_per_short = round(total / delivered, 1) if delivered else None

    return {
        "total_sec": round(total, 2),
        "shorts_delivered": delivered,
        "sec_per_short": sec_per_short,
        "split": {
            "claude_sec": round(claude_sec, 2),
            "ffmpeg_sec": round(ffmpeg_sec, 2),
            "io_sec": round(io_sec, 2),
        },
        "lanes": lane_out,
        "top_steps": top_steps,
        "guardrail": guardrail,
    }


def render_html(rep, src_label=""):
    s = rep["split"]
    total = s["claude_sec"] + s["ffmpeg_sec"] + s["io_sec"]
    if total <= 0:
        total = 1.0

    def pct(v):
        return round(100.0 * v / total)

    g = rep["guardrail"]
    mean = g["mean_grade"]
    gold = g["tier_mix"].get("GOLD", 0)
    fails = g["fail_count"]
    n_lanes = len(rep["lanes"]) or 1
    n_spans = rep["shorts_delivered"]

    # lane timeline bars: position each top-level step proportionally across
    # the global timeline, colored by kind.
    all_t0 = []
    all_t1 = []
    for lane in rep["lanes"]:
        for sp in lane["spans"]:
            for st in sp["steps"]:
                all_t0.append(st["t0"])
                all_t1.append(st["t1"])
    tmin = min(all_t0) if all_t0 else 0.0
    tmax = max(all_t1) if all_t1 else 1.0
    span_w = (tmax - tmin) or 1.0

    def color(kind):
        if kind == "claude":
            return "var(--sapphire)"
        if kind == "ffmpeg":
            return "var(--cobalt)"
        return "#3a4654"

    lane_rows = []
    for lane in rep["lanes"]:
        segs = []
        for sp in lane["spans"]:
            for st in sp["steps"]:
                left = 100.0 * (st["t0"] - tmin) / span_w
                width = 100.0 * (st["t1"] - st["t0"]) / span_w
                if width < 0.3:
                    width = 0.3
                segs.append(
                    '<span class="seg" style="left:%.2f%%;width:%.2f%%;background:%s" title="%s %.1fs"></span>'
                    % (left, width, color(st["kind"]), st["label"], st["sec"])
                )
        lane_rows.append(
            '<tr class="lane-row"><td style="width:70px;color:var(--muted)">lane %s</td>'
            '<td><div class="lane">%s</div></td></tr>'
            % (lane["lane"], "".join(segs))
        )

    top_rows = []
    for st in rep["top_steps"]:
        top_rows.append(
            "<tr><td>%s</td><td>%s</td><td class=\"num\">%s</td><td class=\"pct\">×%d</td></tr>"
            % (st["label"], st["kind"] or "", fmt_clock(st["total_sec"]), st["calls"])
        )

    tier_str = " · ".join("%s×%d" % (k, v) for k, v in sorted(g["tier_mix"].items()))

    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>C0BALT_CUT — run throughput report</title>
<style>
  :root{{--carbon:#101418;--panel:#161b22;--line:#222a33;--plat:#E8ECF1;
    --muted:#8a97a6;--sapphire:#2E6BFF;--cobalt:#0047AB;--good:#36d399;--warn:#f5b14c;}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--carbon);color:var(--plat);
    font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:28px}}
  .wrap{{max-width:880px;margin:0 auto}}
  h1{{font-size:15px;letter-spacing:.06em;margin:0 0 2px;text-transform:uppercase}}
  .sub{{color:var(--muted);font-size:12px;margin-bottom:22px}}
  .hero{{display:flex;gap:14px;margin-bottom:24px;flex-wrap:wrap}}
  .card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;
    padding:14px 16px;flex:1;min-width:165px}}
  .card .lab{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
  .card .big{{font-size:26px;font-weight:700;margin-top:6px}}
  .card .big small{{font-size:13px;color:var(--muted);font-weight:400}}
  .sect{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);
    margin:8px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}}
  table{{width:100%;border-collapse:collapse;margin-bottom:26px}}
  td,th{{text-align:left;padding:6px 8px;font-size:13px}}
  th{{color:var(--muted);font-weight:400;font-size:11px;text-transform:uppercase;letter-spacing:.04em}}
  tr+tr td{{border-top:1px solid var(--line)}}
  .bar{{height:8px;border-radius:4px;display:inline-block;vertical-align:middle}}
  .bar.claude{{background:var(--sapphire)}} .bar.ffmpeg{{background:var(--cobalt)}} .bar.io{{background:#3a4654}}
  .num{{text-align:right;color:var(--plat);font-variant-numeric:tabular-nums}}
  .pct{{color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}}
  .lane-row td{{padding:4px 8px}}
  .lane{{height:18px;border-radius:3px;position:relative;background:#0e131a;overflow:hidden}}
  .seg{{position:absolute;top:0;height:100%;opacity:.92}}
  .legend{{display:flex;gap:18px;color:var(--muted);font-size:11px;margin:-12px 0 22px}}
  .legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:middle}}
  .foot{{color:var(--muted);font-size:11px;border-top:1px solid var(--line);padding-top:12px}}
  .ok{{color:var(--good)}} .bad{{color:var(--warn)}}
</style></head><body><div class="wrap">
  <h1>C0BALT_CUT &nbsp;·&nbsp; run throughput report</h1>
  <div class="sub">source: {src} &nbsp;·&nbsp; {nspans} short(s) &nbsp;·&nbsp; {nlanes} lane(s)</div>
  <div class="hero">
    <div class="card"><div class="lab">wall-clock / short</div><div class="big">{per_short}</div></div>
    <div class="card"><div class="lab">full run</div><div class="big">{full}</div></div>
    <div class="card"><div class="lab">claude / ffmpeg / io</div><div class="big" style="font-size:18px">{cpct}% / {fpct}% / {ipct}%</div></div>
    <div class="card"><div class="lab">quality (mean grade)</div><div class="big">{mean} <small>{tiers}</small></div>
      <div class="{failcls}">{fails} fail marker(s)</div></div>
  </div>
  <div class="sect">Where the time went</div>
  <table>
    <tr><th>Stage class</th><th></th><th class="num">time</th><th class="pct">share</th></tr>
    <tr><td>Claude steps</td><td style="width:42%"><span class="bar claude" style="width:{cpct}%"></span></td><td class="num">{ctime}</td><td class="pct">{cpct}%</td></tr>
    <tr><td>ffmpeg re-encodes</td><td><span class="bar ffmpeg" style="width:{fpct}%"></span></td><td class="num">{ftime}</td><td class="pct">{fpct}%</td></tr>
    <tr><td>ingest · transcribe · I/O</td><td><span class="bar io" style="width:{ipct}%"></span></td><td class="num">{itime}</td><td class="pct">{ipct}%</td></tr>
  </table>
  <div class="sect">Lane timeline — overlap keeps lanes busy</div>
  <table>{lanes}</table>
  <div class="legend">
    <span><i style="background:var(--sapphire)"></i>Claude</span>
    <span><i style="background:var(--cobalt)"></i>ffmpeg</span>
    <span><i style="background:#3a4654"></i>I/O · setup</span>
  </div>
  <div class="sect">Top per-step costs (summed across spans)</div>
  <table><tr><th>Step</th><th>type</th><th class="num">total</th><th class="pct">calls</th></tr>{top}</table>
  <div class="foot">Report written to <span style="color:var(--plat)">work/&lt;id&gt;/run_timing.json</span> +
    <span style="color:var(--plat)">output/&lt;slug&gt;/_timing.html</span> · guardrail: mean grade {mean}, {fails} fail marker(s).</div>
</div></body></html>""".format(
        src=src_label or "—",
        nspans=n_spans,
        nlanes=n_lanes,
        per_short=fmt_clock(rep["sec_per_short"]) if rep["sec_per_short"] else "—",
        full=fmt_clock(rep["total_sec"]),
        mean=("%g" % mean) if mean is not None else "—",
        tiers=tier_str or ("GOLD×%d" % gold if gold else ""),
        fails=fails,
        failcls="ok" if fails == 0 else "bad",
        cpct=pct(s["claude_sec"]),
        fpct=pct(s["ffmpeg_sec"]),
        ipct=pct(s["io_sec"]),
        ctime=fmt_clock(s["claude_sec"]),
        ftime=fmt_clock(s["ffmpeg_sec"]),
        itime=fmt_clock(s["io_sec"]),
        lanes="".join(lane_rows),
        top="".join(top_rows),
    )


def main():
    if len(sys.argv) < 2:
        log("usage: timing-report.py <run_timing.jsonl> [work_dir] [out_html]")
        return 0
    jsonl = sys.argv[1]
    work_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(jsonl))
    out_html = sys.argv[3] if len(sys.argv) > 3 else None

    try:
        if not os.path.exists(jsonl):
            log("no timing log at %s — nothing to report" % jsonl)
            return 0
        recs = load_records(jsonl)
        rep = build_report(recs, work_dir)
        out_json = os.path.join(work_dir, "run_timing.json")
        json.dump(rep, open(out_json, "w"), indent=2)
        log("wrote %s (%d records)" % (out_json, len(recs)))

        if out_html:
            src_label = os.path.basename(os.path.dirname(out_html)) if os.path.dirname(out_html) else ""
            try:
                os.makedirs(os.path.dirname(out_html), exist_ok=True)
            except Exception:
                pass
            open(out_html, "w").write(render_html(rep, src_label))
            log("wrote %s" % out_html)
    except Exception as e:
        log("ERROR (non-fatal): %s" % e)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
