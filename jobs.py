"""Job state and execution.

Named `jobs` rather than `queue` so it does not shadow the standard library
module the worker builds on.
"""
import collections
import subprocess
import threading
import time
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
        self.cancelled = False
        self.process = None
        self.command = None
        self._filename_is_final = False
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
        # Exposed so the queue can terminate this job on request.
        job.process = process
        for line in process.stdout:
            line = line.rstrip("\n")
            if not line:
                continue
            job.note(line)
            update = ytdlp.parse_progress(line)
            final = update.pop("final", False)
            if "filename" in update:
                # A merged or extracted name is the real output; provisional
                # per-format fragments must never overwrite it.
                if job._filename_is_final and not final:
                    update.pop("filename")
                elif final:
                    job._filename_is_final = True
            for key, value in update.items():
                setattr(job, key, value)
        returncode = process.wait()
        if job.cancelled:
            # Terminating yt-dlp makes it exit non-zero. That is the outcome
            # the user asked for, not a failure to report back to them.
            job.status = "cancelled"
        elif returncode == 0:
            job.status = "done"
            job.percent = 100
        else:
            job.status = "error"
            job.error = "yt-dlp exited with an error. See log for details."
    except FileNotFoundError:
        job.status = "error"
        job.error = NO_YTDLP
    except Exception as error:  # noqa: BLE001
        if job.cancelled:
            job.status = "cancelled"
        else:
            job.status = "error"
            job.error = str(error)
    finally:
        job.stage = None
        job.process = None


CANCELLED_BY_USER = "Cancelled."


class JobQueue:
    """A single-worker FIFO queue.

    One job runs at a time: kinder to rate limits and far easier to read than
    interleaved progress. Pending work can be dropped without disturbing what
    is already running, and the running job can be cancelled outright.
    """

    def __init__(self, runner):
        self.runner = runner
        self.jobs = {}
        self._pending = collections.deque()
        self._condition = threading.Condition()
        self._stopping = False
        self._shutdown = False
        self.current = None
        self._worker = None

    def start(self):
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()
        return self

    def add(self, job):
        with self._condition:
            self.jobs[job.id] = job
            self._pending.append(job)
            self._condition.notify_all()
        return job

    def _work(self):
        while True:
            with self._condition:
                while not self._pending and not self._shutdown:
                    self._condition.wait()
                if self._shutdown:
                    return
                job = self._pending.popleft()
                self.current = job
            try:
                self.runner(job)
            except Exception as error:  # noqa: BLE001
                # One bad job must never take the queue down with it.
                job.status = "error"
                job.error = str(error)
            finally:
                with self._condition:
                    self.current = None
                    self._condition.notify_all()

    def stop_after_current(self):
        """Drop everything pending. Whatever is running is left to finish."""
        with self._condition:
            self._stopping = True
            dropped = list(self._pending)
            self._pending.clear()
            for job in dropped:
                job.status = "cancelled"
            self._condition.notify_all()
        return dropped

    def cancel(self, job_id):
        """Cancel one job, whether it is waiting or already running."""
        with self._condition:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            if job in self._pending:
                self._pending.remove(job)
                job.status = "cancelled"
                self._condition.notify_all()
                return True
            if self.current is job:
                job.cancelled = True
                process = job.process
                if process is not None:
                    try:
                        process.terminate()
                    except OSError:
                        pass
                return True
        return False

    def wait_idle(self, timeout=5):
        """Block until nothing is running or pending. For tests and shutdown."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._pending or self.current is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(remaining, 0.05))
        return True

    def snapshot(self):
        with self._condition:
            return [job.to_dict() for job in self.jobs.values()]

    def state(self):
        with self._condition:
            return {
                "stopping": self._stopping,
                "running": self.current.id if self.current else None,
                "pending": len(self._pending),
            }
