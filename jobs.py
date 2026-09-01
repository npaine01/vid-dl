"""Job state and execution.

Named `jobs` rather than `queue` so it does not shadow the standard library
module the worker builds on.
"""
import subprocess
import uuid

import ytdlp

LOG_LINES = 80

NO_YTDLP = "yt-dlp isn't installed. Re-run the launcher to install it."
NO_FFMPEG_FOR_MP3 = (
    "MP3 extraction needs ffmpeg, and no working copy was found. "
    "Install it with: brew install ffmpeg (then try again)."
)


class Job:
    def __init__(self, url, mode="video", quality=ytdlp.DEFAULT_QUALITY,
                 sub_lang=None, title=None):
        self.id = uuid.uuid4().hex[:12]
        self.url = url
        self.mode = mode
        self.quality = quality
        self.sub_lang = sub_lang
        self.title = title
        self.status = "queued"
        self.stage = None
        self.percent = 0
        self.size = None
        self.filename = None
        self.error = None
        self.log = []

    def to_dict(self):
        return {
            "id": self.id, "url": self.url, "mode": self.mode,
            "quality": self.quality, "sub_lang": self.sub_lang,
            "title": self.title, "status": self.status, "stage": self.stage,
            "percent": self.percent, "size": self.size,
            "filename": self.filename, "error": self.error, "log": self.log,
        }

    def note(self, line):
        self.log.append(line)
        del self.log[:-LOG_LINES]


def _spawn(command):
    return subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)


def run_download(job, command, spawn=_spawn, ffmpeg=True):
    """Run one download to completion, updating `job` as output arrives."""
    if job.mode == "audio" and not ffmpeg:
        job.status = "error"
        job.error = NO_FFMPEG_FOR_MP3
        return

    job.status = "running"
    job.stage = "downloading"
    try:
        process = spawn(command)
        for line in process.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            job.note(line)
            for key, value in ytdlp.parse_progress(line).items():
                setattr(job, key, value)
        if process.wait() == 0:
            job.status = "done"
            job.percent = 100
        else:
            job.status = "error"
            job.error = "yt-dlp exited with an error. See log for details."
    except FileNotFoundError:
        job.status = "error"
        job.error = NO_YTDLP
    except Exception as error:  # noqa: BLE001
        job.status = "error"
        job.error = str(error)
    finally:
        job.stage = None
