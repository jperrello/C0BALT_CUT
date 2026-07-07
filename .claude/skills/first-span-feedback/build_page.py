import os, json, argparse, html


def loadjson(p):
    if not p or not os.path.isfile(p):
        return None
    try:
        return json.load(open(p))
    except Exception:
        return None


def esc(s):
    return html.escape(str(s))


def row(cls, k, v, flag=False):
    vcls = "v flag" if flag else "v"
    return ('<div class="sig"><span class="dot %s"></span>'
            '<span class="k">%s</span>'
            '<span class="%s">%s</span></div>') % (cls, esc(k), vcls, esc(v))


# Render the grade.json retention signals as color-dotted rows, flagging any
# that fail the swipe-gate polarity grade-clip enforces. The failing signal is
# the one the reviewer must confirm on screen.
def sigrows(grade):
    sig = (grade or {}).get("signals") or {}
    caps = (grade or {}).get("hard_caps") or []
    rows = []

    if "frame1_is_face" in sig:
        ok = bool(sig["frame1_is_face"])
        rows.append(row("ok" if ok else "bad", "frame 1 is a face",
                        "YES" if ok else "NO — face withheld", flag=not ok))

    for cap in caps:
        rows.append(row("bad", "hard cap", "%s → grade ≤ 40" % cap, flag=True))

    if "letterbox_bars" in sig:
        lb = bool(sig["letterbox_bars"])
        rows.append(row("bad" if lb else "ok", "letterbox bars",
                        "present" if lb else "none", flag=lb))

    if "credit_lit_at_open" in sig:
        cl = bool(sig["credit_lit_at_open"])
        rows.append(row("bad" if cl else "ok", "credit lit at open",
                        "yes" if cl else "no", flag=cl))

    def num(key, label, warn_over, unit="s"):
        if key not in sig or sig[key] is None:
            return
        try:
            v = float(sig[key])
        except Exception:
            return
        cls = "warn" if v > warn_over else "ok"
        rows.append(row(cls, label, "%.1f%s" % (v, unit)))

    num("first_visual_change_sec", "first visual change", 3.0)
    num("first_payoff_offset", "first payoff offset", 3.0)
    num("longest_static_gap", "longest static gap", 5.0)
    num("max_residual_silence", "max residual silence", 0.5)

    if "opening_caption_words" in sig and sig["opening_caption_words"] is not None:
        try:
            w = int(sig["opening_caption_words"])
            rows.append(row("ok" if w > 0 else "warn", "opening caption words", str(w)))
        except Exception:
            pass

    if "terminal_loop_score" in sig and sig["terminal_loop_score"] is not None:
        try:
            rows.append(row("ok", "terminal loop score", "%.2f" % float(sig["terminal_loop_score"])))
        except Exception:
            pass

    if not rows:
        rows.append(row("warn", "signals", "(none recorded)"))
    return "\n        ".join(rows)


def tier_class(tier):
    t = (tier or "").upper()
    if t == "GOLD":
        return "gold"
    if t == "FIXABLE":
        return "fixable"
    return "dross"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("grade")
    ap.add_argument("out_html")
    ap.add_argument("--template", default=os.path.join(os.path.dirname(__file__), "page-template.html"))
    ap.add_argument("--video", default="span0.mp4")
    ap.add_argument("--slug", default="")
    ap.add_argument("--span", default="00")
    ap.add_argument("--dur", type=float, default=0.0)
    ap.add_argument("--source", default="")
    a = ap.parse_args()

    grade = loadjson(a.grade) or {}
    tpl = open(a.template).read()

    g = grade.get("grade", "?")
    tier = grade.get("tier", "?")
    src = a.source or grade.get("source", "") or "(unknown source)"

    phase = "%s · span %s · pre-fanout gate" % (a.slug or "span0", a.span)
    dur = ("%.1fs" % a.dur) if a.dur > 0 else "—"

    if a.video and os.path.isfile(os.path.join(os.path.dirname(a.out_html), a.video)):
        player = ('<video src="%s" muted playsinline autoplay loop></video>'
                  % esc(a.video))
    else:
        player = ('<div class="ph">▶ %s<br>1080×1920 · %s<br>'
                  '<span style="opacity:.6">(plays through once for the recording)</span></div>'
                  % (esc(a.video), dur))

    meta = "source: %s<br>1080×1920 · %s<br>chain: full · pre-fanout" % (esc(src), dur)

    verdict = ("Watch the player play span 0 through once and read every retention "
               "signal above. Name any SYSTEMIC defect a later span would repeat, "
               "or return clean. The flagged signals are where grade-clip already "
               "sees a swipe-gate risk — confirm or clear each on screen.")

    repl = {
        "{{PHASE}}": esc(phase),
        "{{PLAYER}}": player,
        "{{GRADE}}": esc(g),
        "{{TIER_CLASS}}": tier_class(tier),
        "{{TIER_LABEL}}": esc(tier),
        "{{META}}": meta,
        "{{SIGNALS}}": sigrows(grade),
        "{{VERDICT_TAG}}": "Reviewer verdict — pending",
        "{{VERDICT}}": esc(verdict),
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)

    os.makedirs(os.path.dirname(os.path.abspath(a.out_html)), exist_ok=True)
    with open(a.out_html, "w") as f:
        f.write(tpl)
    print(a.out_html)


if __name__ == "__main__":
    main()
