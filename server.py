#!/usr/bin/env python3
"""
YouTube Downloader - local server
Pure standard library (no Flask/etc needed). Wraps yt-dlp and serves a
simple web UI on localhost so you never have to touch the terminal.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = 8642
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Default save location: Downloads/YT (falls back to a local "downloads"
# folder next to this script if that path doesn't exist for some reason).
HOME = os.path.expanduser("~")
DEFAULT_OUTPUT_DIR = os.path.join(HOME, "Downloads", "YT")
if not os.path.isdir(os.path.dirname(DEFAULT_OUTPUT_DIR)):
    DEFAULT_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "downloads")
os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

JOBS = {}
JOBS_LOCK = threading.Lock()

PERCENT_RE = re.compile(r"\[download\]\s+([\d.]+)%")
DEST_RE = re.compile(r"(?:Destination|Merging formats into):?\s*\"?([^\"\n]+)\"?$")
SIZE_RE = re.compile(r"\[download\]\s+[\d.]+%\s+of\s+~?\s*([\d.]+\s?\S+?)(?:\s+at\s|\s+in\s|\s*$)")

# Default max resolution for video downloads when the user doesn't pick one.
DEFAULT_QUALITY = "1080"
VALID_QUALITIES = {"best", "2160", "1440", "1080", "720", "480"}


def build_command(url, mode, quality=DEFAULT_QUALITY, subs=False):
    base = [sys.executable, "-m", "yt_dlp", "--newline", "--no-playlist"]
    outtmpl = os.path.join(DEFAULT_OUTPUT_DIR, "%(title)s.%(ext)s")
    if mode == "audio":
        base += ["-x", "--audio-format", "mp3"]
    else:
        cap = None if quality not in VALID_QUALITIES or quality == "best" else quality
        if FFMPEG_AVAILABLE:
            if cap:
                fmt = f"bestvideo[height<={cap}]+bestaudio/best[height<={cap}]"
            else:
                fmt = "bv*+ba/b"
        else:
            fmt = f"best[height<={cap}]/b" if cap else "b"
        base += ["-f", fmt, "--merge-output-format", "mp4"]
        if subs:
            # Prefer real English captions; fall back to auto-generated ones
            # if that's all the video has. Saved as a separate .srt file
            # next to the video (converted from YouTube's vtt when ffmpeg
            # is available; left as .vtt otherwise).
            base += ["--write-subs", "--write-auto-subs", "--sub-langs", "en.*"]
            if FFMPEG_AVAILABLE:
                base += ["--convert-subs", "srt"]
    base += ["-o", outtmpl, url]
    return base


def run_job(job_id, url, mode, quality=DEFAULT_QUALITY, subs=False):
    job = JOBS[job_id]

    if mode == "audio" and not FFMPEG_AVAILABLE:
        job["status"] = "error"
        job["error"] = (
            "MP3 extraction needs ffmpeg, which isn't installed. "
            "Install it with: brew install ffmpeg (then try again)."
        )
        return

    subs = subs and mode == "video"
    if subs and not FFMPEG_AVAILABLE:
        job["log"].append(
            "(ffmpeg not found - subtitles will be saved as .vtt instead of "
            ".srt. Install ffmpeg for automatic conversion.)"
        )

    cmd = build_command(url, mode, quality, subs)
    job["status"] = "running"
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=DEFAULT_OUTPUT_DIR,
        )
        job["pid"] = proc.pid
        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            job["log"].append(line)
            job["log"] = job["log"][-80:]
            m = PERCENT_RE.search(line)
            if m:
                job["percent"] = float(m.group(1))
            s = SIZE_RE.search(line)
            if s:
                job["size"] = s.group(1).strip()
            d = DEST_RE.search(line)
            if d:
                job["filename"] = os.path.basename(d.group(1))
        proc.wait()
        if proc.returncode == 0:
            job["status"] = "done"
            job["percent"] = 100
        else:
            job["status"] = "error"
            job["error"] = "yt-dlp exited with an error. See log for details."
    except FileNotFoundError:
        job["status"] = "error"
        job["error"] = "yt-dlp isn't installed. Re-run the launcher to install it."
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)


INDEX_HTML_PATH = os.path.join(SCRIPT_DIR, "index.html")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            try:
                with open(INDEX_HTML_PATH, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                body = b"<h1>index.html missing</h1>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/status":
            qs = parse_qs(parsed.query)
            job_id = qs.get("id", [None])[0]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                data = dict(job) if job else None
            if data is None:
                self._send_json({"error": "unknown job"}, 404)
            else:
                self._send_json(data)
        elif parsed.path == "/api/info":
            self._send_json({
                "output_dir": DEFAULT_OUTPUT_DIR,
                "ffmpeg_available": FFMPEG_AVAILABLE,
                "default_quality": DEFAULT_QUALITY,
            })
        elif parsed.path == "/api/open-folder":
            try:
                subprocess.Popen(["open", DEFAULT_OUTPUT_DIR])
            except Exception:
                pass
            self._send_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/download":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                payload = {}
            url = (payload.get("url") or "").strip()
            mode = payload.get("mode") if payload.get("mode") in ("video", "audio") else "video"
            quality = payload.get("quality")
            if quality not in VALID_QUALITIES:
                quality = DEFAULT_QUALITY
            subs = bool(payload.get("subs"))
            if not url:
                self._send_json({"error": "Missing URL"}, 400)
                return
            job_id = uuid.uuid4().hex[:12]
            with JOBS_LOCK:
                JOBS[job_id] = {
                    "id": job_id, "url": url, "mode": mode, "quality": quality,
                    "subs": subs, "status": "starting", "percent": 0, "size": None,
                    "log": [], "filename": None, "error": None,
                }
            t = threading.Thread(target=run_job, args=(job_id, url, mode, quality, subs), daemon=True)
            t.start()
            self._send_json({"id": job_id})
        else:
            self.send_response(404)
            self.end_headers()


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"YouTube Downloader running at {url}")
    print(f"Saving downloads to: {DEFAULT_OUTPUT_DIR}")
    if not FFMPEG_AVAILABLE:
        print("NOTE: ffmpeg not found - video quality will be limited and MP3 "
              "extraction will not work. Install with: brew install ffmpeg")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
