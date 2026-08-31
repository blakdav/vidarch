import os
import re
import glob
import subprocess
import threading
from collections import OrderedDict
from queue import Queue

from flask import Flask, request, jsonify, render_template

OUT_DIR = os.environ.get("OUTPUT_DIR", "/downloads")
WORKERS = int(os.environ.get("WORKERS", "3"))
FORMAT = os.environ.get("YTDLP_FORMAT", "bv*+ba/b")

app = Flask(__name__)

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
UNSAFE_RE = re.compile(r"[^A-Za-z0-9 ._()-]")

jobs = OrderedDict()          # key -> {key, name, status, detail}
jobs_lock = threading.Lock()
work_q = Queue()


def parse_paste(raw):
    """Pull usable multivariant manifests out of a raw Network-tab dump.

    Keeps one URL per video, dropping video-only renditions, segment
    requests, and anything that isn't an HLS manifest.
    """
    found = OrderedDict()
    for chunk in raw.replace(",", "\n").splitlines():
        url = chunk.strip().strip("\"'")
        if not url.startswith("http"):
            continue
        if ".m3u8" not in url:
            continue
        if "st=video" in url:
            continue
        if "sf=fmp4" not in url and "/av/primary/" not in url:
            continue
        m = UUID_RE.search(url)
        key = m.group(0) if m else url
        found.setdefault(key, url)
    return found


def safe_name(text, fallback):
    name = UNSAFE_RE.sub("", (text or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] if name else fallback


def already_have(name):
    pattern = os.path.join(OUT_DIR, glob.escape(name) + ".*")
    return bool(glob.glob(pattern))


def set_status(key, status, detail=""):
    with jobs_lock:
        if key in jobs:
            jobs[key]["status"] = status
            jobs[key]["detail"] = detail


def worker():
    while True:
        key, url, name = work_q.get()
        try:
            set_status(key, "downloading")
            target = os.path.join(OUT_DIR, name + ".%(ext)s")
            proc = subprocess.run(
                [
                    "yt-dlp",
                    "-f", FORMAT,
                    "--no-progress",
                    "--no-playlist",
                    "--retries", "3",
                    "-o", target,
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=1800,
            )
            if proc.returncode == 0:
                set_status(key, "done")
            else:
                tail = (proc.stderr or "").strip().splitlines()
                set_status(key, "failed", tail[-1] if tail else "unknown error")
        except subprocess.TimeoutExpired:
            set_status(key, "failed", "timed out")
        except Exception as exc:  # noqa: BLE001
            set_status(key, "failed", str(exc))
        finally:
            work_q.task_done()


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/preview")
def preview():
    data = request.get_json(force=True)
    found = parse_paste(data.get("urls", ""))
    titles = [t.strip() for t in data.get("titles", "").splitlines() if t.strip()]

    items = []
    for i, key in enumerate(found):
        proposed = titles[i] if i < len(titles) else ""
        name = safe_name(proposed, key)
        items.append({
            "key": key,
            "name": name,
            "have": already_have(name),
        })

    return jsonify({
        "items": items,
        "title_count": len(titles),
        "aligned": len(titles) == 0 or len(titles) == len(found),
    })


@app.post("/api/start")
def start():
    data = request.get_json(force=True)
    found = parse_paste(data.get("urls", ""))
    titles = [t.strip() for t in data.get("titles", "").splitlines() if t.strip()]

    queued = 0
    for i, (key, url) in enumerate(found.items()):
        name = safe_name(titles[i] if i < len(titles) else "", key)
        if already_have(name):
            continue
        with jobs_lock:
            if key in jobs and jobs[key]["status"] in ("queued", "downloading", "done"):
                continue
            jobs[key] = {"key": key, "name": name, "status": "queued", "detail": ""}
        work_q.put((key, url, name))
        queued += 1

    return jsonify({"queued": queued})


@app.get("/api/status")
def status():
    with jobs_lock:
        current = list(jobs.values())
    counts = {"queued": 0, "downloading": 0, "done": 0, "failed": 0}
    for job in current:
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    return jsonify({"jobs": current, "counts": counts})


@app.post("/api/clear")
def clear():
    with jobs_lock:
        for key in [k for k, v in jobs.items() if v["status"] in ("done", "failed")]:
            del jobs[key]
    return jsonify({"ok": True})


os.makedirs(OUT_DIR, exist_ok=True)
for _ in range(WORKERS):
    threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
