import os, json, argparse


# Emit the shot-scraper `video` storyboard. The page is served over a real
# http://127.0.0.1 origin (Chromium blocks <video> autoplay on file:// origins),
# so the storyboard's `server:` key launches a throwaway python http.server in
# the preview dir; shot-scraper starts it, records the page, tears it down.
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("preview_dir")
    ap.add_argument("out_yml")
    ap.add_argument("--port", type=int, default=8917)
    ap.add_argument("--dur", type=float, default=30.0)
    ap.add_argument("--html", default="span0-review.html")
    ap.add_argument("--out", default="span0-demo.webm")
    a = ap.parse_args()

    pdir = os.path.abspath(a.preview_dir)
    pause = round(max(2.0, a.dur + 1.5), 1)

    doc = {
        "output": os.path.join(pdir, a.out),
        "server": ["python3", "-m", "http.server", str(a.port), "--directory", pdir],
        "url": "http://127.0.0.1:%d/%s" % (a.port, a.html),
        "viewport": {"width": 1080, "height": 1920},
        "cursor": False,
        "wait_for": "video",
        "scenes": [
            {
                "name": "Play span 0 through once",
                "do": [
                    {"js": "document.querySelector('video').play()"},
                    {"pause": pause},
                ],
            }
        ],
    }

    # JSON is valid YAML — shot-scraper parses it either way, and this keeps the
    # emit dependency-free (no PyYAML).
    os.makedirs(pdir, exist_ok=True)
    with open(a.out_yml, "w") as f:
        json.dump(doc, f, indent=2)
    print(a.out_yml)


if __name__ == "__main__":
    main()
