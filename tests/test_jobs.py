"""Tests for jobs.py -- job state and download execution."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jobs


class FakeProcess:
    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self._returncode = returncode
        self.pid = 4242

    def wait(self):
        return self._returncode


def spawning(*args, **kwargs):
    process = FakeProcess(*args, **kwargs)
    return lambda command: process


class TestJobState(unittest.TestCase):
    def test_starts_queued_with_no_progress(self):
        job = jobs.Job(url="https://example.com/x")
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.percent, 0)

    def test_gives_every_job_a_distinct_id(self):
        self.assertNotEqual(jobs.Job(url="a").id, jobs.Job(url="b").id)

    def test_serializes_to_a_dict_for_the_api(self):
        job = jobs.Job(url="https://example.com/x", mode="audio")
        payload = job.to_dict()
        self.assertEqual(payload["url"], "https://example.com/x")
        self.assertEqual(payload["mode"], "audio")
        self.assertIn("status", payload)


class TestRunDownload(unittest.TestCase):
    def test_marks_the_job_done_on_a_clean_exit(self):
        job = jobs.Job(url="x")
        jobs.run_download(job, ["yt-dlp"], spawn=spawning(["[download] 100%"]))
        self.assertEqual(job.status, "done")
        self.assertEqual(job.percent, 100)

    def test_tracks_progress_from_the_output(self):
        job = jobs.Job(url="x")
        jobs.run_download(job, ["yt-dlp"], spawn=spawning([
            "[download] Destination: /tmp/Clip.mp4",
            "[download]  50.0% of ~ 10.00MiB at 1.00MiB/s ETA 00:10",
        ]))
        self.assertEqual(job.filename, "Clip.mp4")
        self.assertEqual(job.size, "10.00MiB")

    def test_marks_the_job_failed_on_a_nonzero_exit(self):
        job = jobs.Job(url="x")
        jobs.run_download(job, ["yt-dlp"],
                          spawn=spawning(["ERROR: unavailable"], returncode=1))
        self.assertEqual(job.status, "error")
        self.assertTrue(job.error)

    def test_explains_how_to_recover_when_yt_dlp_is_missing(self):
        job = jobs.Job(url="x")

        def missing(command):
            raise FileNotFoundError(command[0])

        jobs.run_download(job, ["yt-dlp"], spawn=missing)
        self.assertEqual(job.status, "error")
        self.assertIn("yt-dlp", job.error)

    def test_keeps_the_log_bounded(self):
        job = jobs.Job(url="x")
        jobs.run_download(job, ["yt-dlp"],
                          spawn=spawning([f"line {n}" for n in range(500)]))
        self.assertLessEqual(len(job.log), jobs.LOG_LINES)
        self.assertEqual(job.log[-1], "line 499")

    def test_refuses_mp3_extraction_without_ffmpeg_before_spawning(self):
        job = jobs.Job(url="x", mode="audio")

        def must_not_run(command):
            raise AssertionError("should not have spawned")

        jobs.run_download(job, ["yt-dlp"], spawn=must_not_run, ffmpeg=False)
        self.assertEqual(job.status, "error")
        self.assertIn("ffmpeg", job.error)


class TestCancellationDuringDownload(unittest.TestCase):
    def test_exposes_the_process_while_running_so_it_can_be_terminated(self):
        job = jobs.Job(url="x")
        process = FakeProcess(["[download] 10%", "[download] 20%"])
        lines, seen = process.stdout, []

        def watched():
            for line in lines:
                seen.append(job.process)
                yield line

        process.stdout = watched()
        jobs.run_download(job, ["yt-dlp"], spawn=lambda command: process)
        self.assertIs(seen[0], process)

    def test_releases_the_process_handle_once_finished(self):
        job = jobs.Job(url="x")
        jobs.run_download(job, ["yt-dlp"], spawn=spawning(["[download] 10%"]))
        self.assertIsNone(job.process)

    def test_reports_a_cancelled_job_as_cancelled_not_failed(self):
        """Terminating yt-dlp makes it exit non-zero, which must not be
        presented to the user as an error they need to investigate."""
        job = jobs.Job(url="x")
        job.cancelled = True
        jobs.run_download(job, ["yt-dlp"],
                          spawn=spawning(["[download] 10%"], returncode=-15))
        self.assertEqual(job.status, "cancelled")
        self.assertIsNone(job.error)

    def test_still_reports_a_genuine_failure_as_an_error(self):
        job = jobs.Job(url="x")
        jobs.run_download(job, ["yt-dlp"],
                          spawn=spawning(["ERROR: nope"], returncode=1))
        self.assertEqual(job.status, "error")


class TestFilenameSelection(unittest.TestCase):
    def test_the_merged_name_wins_over_earlier_fragments(self):
        job = jobs.Job(url="x")
        jobs.run_download(job, ["yt-dlp"], spawn=spawning([
            "[download] Destination: /tmp/Clip.en.vtt",
            "[download] Destination: /tmp/Clip.f399.mp4",
            "[download] Destination: /tmp/Clip.f251.webm",
            '[Merger] Merging formats into "/tmp/Clip.mp4"',
        ]))
        self.assertEqual(job.filename, "Clip.mp4")

    def test_a_later_fragment_does_not_replace_the_final_name(self):
        job = jobs.Job(url="x")
        jobs.run_download(job, ["yt-dlp"], spawn=spawning([
            '[Merger] Merging formats into "/tmp/Clip.mp4"',
            "[download] Destination: /tmp/Clip.f251.webm",
        ]))
        self.assertEqual(job.filename, "Clip.mp4")

    def test_falls_back_to_a_fragment_when_nothing_merged(self):
        job = jobs.Job(url="x")
        jobs.run_download(job, ["yt-dlp"], spawn=spawning([
            "[download] Destination: /tmp/Clip.f399.mp4",
        ]))
        self.assertEqual(job.filename, "Clip.f399.mp4")
