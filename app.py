import os
import re
import glob
import shlex
import subprocess
import threading
from collections import OrderedDict
from queue import Queue

from flask import Flask, request, jsonify, render_template

OUT_DIR = os.environ.get("OUTPUT_DIR", "/downloads")
WORKERS = int(os.environ.get("WORKERS", "3"))
FORMAT = os.environ.get("YTDLP_FORMAT", "bv*+ba/b")
ARCHIVE = os.path.join(OUT_DIR, ".vidarch-archive")

app = Flask(__name__)

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
UNSAFE_RE = re.compile(r"[^A-Za-z0-9 ._()&,'\[\]+-]")
SKIPPED_FRAG_RE = re.compile(r"Skipping fragment", re.IGNORECASE)
VIDEO_ID_RE = re.compile(r"/(?:video/)?(\d{6,})(?:[/?#]|$)")
EXT_SUFFIX = ".%(ext)s"

jobs = OrderedDict()          # key -> {key, name, status, detail}
jobs_lock = threading.Lock()
work_q = Queue()


def dedupe_key(url):
    """Stable identity for a video across re-pastes.

    Signed manifest URLs change every capture, so fall back to the media
    UUID in the path. Ordinary page URLs are stable once the query string
    is dropped.
    """
    if ".m3u8" in url:
        found = UUID_RE.search(url)
        if found:
            return found.group(0)
    return url.split("?")[0]


ASSET_EXTS = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".map", ".json", ".xml", ".txt",
    ".ts", ".m4s", ".aac", ".vtt", ".srt",
)


def usable_manifest(url):
    """Drop video-only renditions and segment requests from a raw dump."""
    if "st=video" in url:
        return False
    return "sf=fmp4" in url or "/av/primary/" in url


def is_asset(url):
    """Page furniture swept up by a broad network-panel copy."""
    path = url.split("?")[0].split("#")[0].lower()
    return path.endswith(ASSET_EXTS)


def parse_input(raw):
    """Accept three line shapes, mixed freely:

    -o "01 - Some Title.%(ext)s" https://host/video/123
    https://host/video/123
    https://cdn.example/.../playlist.m3u8?...
    """
    items = OrderedDict()
    for line in raw.replace("\r", "").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        name = None
        url = None

        if line.startswith("-o ") or " -o " in line:
            try:
                parts = shlex.split(line)
            except ValueError:
                continue
            for i, part in enumerate(parts):
                if part == "-o" and i + 1 < len(parts):
                    name = parts[i + 1]
                elif part.startswith("http"):
                    url = part
        else:
            candidate = line.strip("\"'")
            if candidate.startswith("http"):
                url = candidate

        if not url:
            continue
        if ".m3u8" in url:
            if not usable_manifest(url):
                continue
        elif name is None and is_asset(url):
            # Unnamed page furniture from a broad copy. An explicit -o means
            # the line was written deliberately, so leave it alone.
            continue

        key = dedupe_key(url)
        if key not in items:
            items[key] = {"key": key, "url": url, "name": name}

    return items


def safe_name(name):
    if not name:
        return None
    stem = name[:-len(EXT_SUFFIX)] if name.endswith(EXT_SUFFIX) else name
    stem = UNSAFE_RE.sub("", stem).strip(" .")
    stem = re.sub(r"\s+", " ", stem)
    return stem[:150] or None


def target_dir(folder):
    if not folder:
        return OUT_DIR
    clean = UNSAFE_RE.sub("", folder).strip(" ./")
    return os.path.join(OUT_DIR, clean) if clean else OUT_DIR


def already_have(directory, stem):
    if not stem:
        return False
    return bool(glob.glob(os.path.join(directory, glob.escape(stem) + ".*")))


def set_status(key, status, detail=""):
    with jobs_lock:
        if key in jobs:
            jobs[key]["status"] = status
            jobs[key]["detail"] = detail


def forget_from_archive(url):
    """Remove a video's archive entry so a retry isn't skipped.

    yt-dlp records a download the moment it exits cleanly, including when it
    gave up on fragments along the way. Dropping the line lets the next run
    fetch it again.
    """
    found = VIDEO_ID_RE.search(url)
    if not found or not os.path.exists(ARCHIVE):
        return
    video_id = found.group(1)
    try:
        with open(ARCHIVE, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
        kept = [ln for ln in lines if not ln.rstrip().endswith(" " + video_id)]
        if len(kept) != len(lines):
            with open(ARCHIVE, "w", encoding="utf-8") as handle:
                handle.writelines(kept)
    except OSError:
        pass


def worker():
    while True:
        key, url, stem, directory, referer = work_q.get()
        try:
            set_status(key, "downloading")
            os.makedirs(directory, exist_ok=True)
            template = (stem + EXT_SUFFIX) if stem else "%(title)s" + EXT_SUFFIX

            cmd = [
                "yt-dlp",
                "-f", FORMAT,
                "--no-progress",
                "--no-playlist",
                "--no-warnings",
                "--retries", "10",
                "--fragment-retries", "25",
                "--download-archive", ARCHIVE,
                "-P", directory,
                "-o", template,
            ]
            if referer:
                cmd += ["--referer", referer]
            cmd.append(url)

            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            output = (proc.stdout or "") + (proc.stderr or "")

            if proc.returncode != 0:
                tail = (proc.stderr or "").strip().splitlines()
                set_status(key, "failed", tail[-1] if tail else "unknown error")
            elif SKIPPED_FRAG_RE.search(output):
                # yt-dlp exits 0 after giving up on individual fragments, so the
                # file looks complete but has gaps. Better to flag it than to
                # record a silently damaged archive.
                dropped = len(SKIPPED_FRAG_RE.findall(output))
                forget_from_archive(url)
                set_status(
                    key, "failed",
                    f"{dropped} fragment(s) missing — file incomplete, retry it",
                )
            else:
                set_status(key, "done")
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
    found = parse_input(data.get("input", ""))
    directory = target_dir(data.get("folder", ""))

    items = []
    for entry in found.values():
        stem = safe_name(entry["name"])
        items.append({
            "key": entry["key"],
            "name": stem or "(named by source)",
            "named": bool(stem),
            "have": already_have(directory, stem),
            "manifest": ".m3u8" in entry["url"],
        })

    return jsonify({"items": items, "folder": directory})


@app.post("/api/start")
def start():
    data = request.get_json(force=True)
    found = parse_input(data.get("input", ""))
    directory = target_dir(data.get("folder", ""))
    referer = (data.get("referer", "") or "").strip()

    queued = 0
    for entry in found.values():
        stem = safe_name(entry["name"])
        if already_have(directory, stem):
            continue
        with jobs_lock:
            existing = jobs.get(entry["key"])
            if existing and existing["status"] in ("queued", "downloading", "done"):
                continue
            jobs[entry["key"]] = {
                "key": entry["key"],
                "name": stem or entry["url"].split("/")[-1][:60],
                "status": "queued",
                "detail": "",
            }
        work_q.put((entry["key"], entry["url"], stem, directory, referer))
        queued += 1

    return jsonify({"queued": queued})


@app.get("/api/status")
def status():
    with jobs_lock:
        current = list(jobs.values())
    counts = {}
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
