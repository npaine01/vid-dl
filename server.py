#!/usr/bin/env python3
"""vid-dl - local server.

Pure standard library. Wraps yt-dlp and serves a small web UI on localhost.
Routing and static files only: command construction lives in ytdlp.py, job
execution in jobs.py, and ffmpeg discovery in media.py.
"""
import json
import os
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import jobs
import media
import ytdlp

PORT = 8642
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

HOME = os.path.expanduser("~")
OUTPUT_DIR = os.path.join(HOME, "Downloads", "YT")
if not os.path.isdir(os.path.dirname(OUTPUT_DIR)):
    OUTPUT_DIR = os.path.join(SCRIPT_DIR, "downloads")
os.makedirs(OUTPUT_DIR, exist_ok=True)

FFMPEG = media.find_ffmpeg()

def _run(job):
    """Queue worker body: build nothing, just run what was prepared."""
    jobs.run_download(job, job.command, ffmpeg=bool(FFMPEG))


QUEUE = jobs.JobQueue(runner=_run).start()

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


def prepare_download(payload, ffmpeg=None, output_dir=None):
    """Validate a download request into a Job and its yt-dlp argv.

    Pure: builds and returns, runs nothing. `ffmpeg` is a path or None -- never
    a boolean, since it is passed straight through to --ffmpeg-location.
    """
    output_dir = output_dir or OUTPUT_DIR
    mode = payload.get("mode") if payload.get("mode") in ("video", "audio") else "video"

    quality = payload.get("quality")
    if quality not in ytdlp.VALID_QUALITIES:
        quality = ytdlp.DEFAULT_QUALITY

    sub_lang = payload.get("sub_lang") or None
    if mode == "audio":
        sub_lang = None

    job = jobs.Job(url=payload["url"].strip(), mode=mode, quality=quality,
                   sub_lang=sub_lang)
    command = ytdlp.build_download_command(
        url=job.url, output_dir=output_dir, mode=mode, quality=quality,
        sub_lang=sub_lang, ffmpeg=ffmpeg)
    return job, command


def enqueue(payload):
    """Validate a download request and add it to the queue."""
    if not (payload.get("url") or "").strip():
        raise ValueError("Missing URL")

    job, command = prepare_download(payload, ffmpeg=FFMPEG)
    job.command = command

    if job.sub_lang and not FFMPEG:
        job.note("(no working ffmpeg - subtitles will be saved as .vtt instead "
                 "of .srt. Install ffmpeg for automatic conversion.)")

    return QUEUE.add(job)


def queue_report():
    """Everything the UI needs to draw the queue in one response."""
    report = QUEUE.state()
    report["jobs"] = QUEUE.snapshot()
    return report


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet

    def _send(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, status=200):
        self._send(json.dumps(obj).encode("utf-8"), "application/json", status)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, ValueError):
            return {}

    def do_GET(self):
        path = urlparse(self.path).path

        if path in STATIC:
            name, content_type = STATIC[path]
            try:
                with open(os.path.join(SCRIPT_DIR, name), "rb") as handle:
                    self._send(handle.read(), content_type)
            except FileNotFoundError:
                self._send(f"{name} missing".encode(), "text/plain", 404)
            return

        if path == "/api/status":
            job_id = parse_qs(urlparse(self.path).query).get("id", [None])[0]
            job = QUEUE.jobs.get(job_id)
            if job is None:
                self._send_json({"error": "unknown job"}, 404)
            else:
                self._send_json(job.to_dict())
            return

        if path == "/api/queue":
            self._send_json(queue_report())
            return

        if path == "/api/info":
            self._send_json({
                "output_dir": OUTPUT_DIR,
                "ffmpeg_available": bool(FFMPEG),
                "ffmpeg_path": FFMPEG,
                "default_quality": ytdlp.DEFAULT_QUALITY,
            })
            return

        if path == "/api/open-folder":
            try:
                subprocess.Popen(["open", OUTPUT_DIR])
            except OSError:
                pass
            self._send_json({"ok": True})
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/download":
            try:
                self._send_json({"id": enqueue(self._read_json()).id})
            except ValueError as error:
                self._send_json({"error": str(error)}, 400)
            return

        if path == "/api/stop":
            dropped = QUEUE.stop_after_current()
            self._send_json({"dropped": len(dropped)})
            return

        if path == "/api/cancel":
            job_id = self._read_json().get("id")
            if QUEUE.cancel(job_id):
                self._send_json({"ok": True})
            else:
                self._send_json({"error": "unknown job"}, 404)
            return

        self.send_response(404)
        self.end_headers()


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"vid-dl running at {url}")
    print(f"Saving downloads to: {OUTPUT_DIR}")
    if not FFMPEG:
        print("NOTE: no working ffmpeg found - video quality will be limited "
              "and MP3 extraction will not work.")
        print("      brew install ffmpeg        (downloads, MP3, merging)")
        print("      brew install ffmpeg-full   (also burns subtitles into video)")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
