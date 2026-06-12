#!/usr/bin/env python3
# rank fully-fetched candidates by outlier score.
# argv: <full_meta_dir> <out.json> [workdir]
# score = 2*velocity + outlier + engagement + peaky
#   velocity   = log10(1 + views/day)              (~0-6; freshness x reach)
#   outlier    = min(10, views / subscribers)      (clip-channel signal: 3x+ = real, 5-10x = strong)
#   engagement = min(5, comments per 1k views)     (talked-about-ness)
#   peaky      = min(3, 10*stdev(heatmap values))  (clippability: spiky replay graph = quotable moments)
import glob, hashlib, json, math, os, statistics, sys
from datetime import datetime, timezone

meta_dir, out_path = sys.argv[1], sys.argv[2]
workdir = sys.argv[3] if len(sys.argv) > 3 else ""

now = datetime.now(timezone.utc)
cands = []
for f in glob.glob(os.path.join(meta_dir, "*.json")):
    try:
        d = json.load(open(f))
    except ValueError:
        continue
    views = d.get("view_count") or 0
    subs = d.get("channel_follower_count") or 0
    comments = d.get("comment_count") or 0
    up = d.get("upload_date") or ""
    if not views or not up:
        continue
    days = max(1, (now - datetime.strptime(up, "%Y%m%d").replace(tzinfo=timezone.utc)).days)
    velocity = math.log10(1 + views / days)
    outlier = min(10.0, views / subs) if subs else 0.0
    engagement = min(5.0, comments / views * 1000)
    hm = [p["value"] for p in (d.get("heatmap") or [])]
    peaky = min(3.0, 10 * statistics.pstdev(hm)) if len(hm) > 1 else 0.0
    url = f"https://www.youtube.com/watch?v={d['id']}"
    seen = bool(workdir) and os.path.isdir(
        os.path.join(workdir, hashlib.sha1(url.encode()).hexdigest()[:10]))
    cands.append({
        "id": d["id"],
        "url": url,
        "title": d.get("title", ""),
        "channel": d.get("channel", ""),
        "duration_min": round((d.get("duration") or 0) / 60),
        "views": views,
        "subs": subs,
        "views_per_day": round(views / days),
        "views_per_sub": round(views / subs, 2) if subs else None,
        "comments_per_1k": round(comments / views * 1000, 2),
        "replay_peakiness": round(peaky, 2),
        "age_days": days,
        "seen": seen,
        "score": round(2 * velocity + outlier + engagement + peaky, 2),
        "components": {
            "velocity": round(velocity, 2),
            "outlier": round(outlier, 2),
            "engagement": round(engagement, 2),
            "peaky": round(peaky, 2),
        },
    })

cands.sort(key=lambda c: -c["score"])
json.dump({"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "candidates": cands},
          open(out_path, "w"), indent=2)

for c in cands:
    mark = " (seen)" if c["seen"] else ""
    print(f"{c['score']:6.2f}  {c['views']:>11,}v  {c['views_per_day']:>9,}v/d  "
          f"x{c['views_per_sub'] or 0:<6} {c['duration_min']:>4}min  "
          f"{c['channel'][:24]:<24} {c['title'][:60]}{mark}")
print(f"\nscout-sources: {len(cands)} candidate(s) -> {out_path}", file=sys.stderr)
