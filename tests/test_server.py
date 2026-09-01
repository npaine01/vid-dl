"""Tests for server.py -- request validation and command assembly.

These cover the seam between the HTTP layer and the modules it drives, which
unit tests of those modules cannot reach.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server


class TestDownloadCommandForRequest(unittest.TestCase):
    def test_passes_the_ffmpeg_path_not_a_flag(self):
        """--ffmpeg-location needs a path. Passing a bool reaches subprocess
        and fails with 'expected str, bytes or os.PathLike object, not bool'."""
        job, command = server.prepare_download(
            {"url": "https://example.com/x"}, ffmpeg="/opt/ffmpeg")
        location = command[command.index("--ffmpeg-location") + 1]
        self.assertIsInstance(location, str)
        self.assertEqual(location, "/opt/ffmpeg")

    def test_every_argument_is_a_string(self):
        _, command = server.prepare_download(
            {"url": "https://example.com/x", "sub_lang": "ja"},
            ffmpeg="/opt/ffmpeg")
        for argument in command:
            self.assertIsInstance(argument, str, f"{argument!r} is not a string")

    def test_omits_the_location_when_no_ffmpeg_was_found(self):
        _, command = server.prepare_download(
            {"url": "https://example.com/x"}, ffmpeg=None)
        self.assertNotIn("--ffmpeg-location", command)

    def test_defaults_an_unknown_mode_to_video(self):
        job, _ = server.prepare_download(
            {"url": "u", "mode": "hologram"}, ffmpeg=None)
        self.assertEqual(job.mode, "video")

    def test_drops_subtitles_for_audio_downloads(self):
        job, command = server.prepare_download(
            {"url": "u", "mode": "audio", "sub_lang": "en"}, ffmpeg="/opt/ffmpeg")
        self.assertIsNone(job.sub_lang)
        self.assertNotIn("--write-subs", command)

    def test_falls_back_to_the_default_quality_for_a_bad_value(self):
        job, _ = server.prepare_download(
            {"url": "u", "quality": "9000"}, ffmpeg=None)
        self.assertEqual(job.quality, server.ytdlp.DEFAULT_QUALITY)


class TestQueueEndpoints(unittest.TestCase):
    """The server owns one queue; these cover the wiring around it."""

    def setUp(self):
        self.ran = []
        server.QUEUE = server.jobs.JobQueue(
            runner=lambda job: (self.ran.append(job.id),
                                setattr(job, "status", "done"))).start()

    def test_enqueue_adds_a_job_and_returns_its_id(self):
        job = server.enqueue({"url": "https://example.com/x"})
        self.assertTrue(server.QUEUE.wait_idle())
        self.assertIn(job.id, self.ran)

    def test_queue_report_lists_jobs_and_queue_state(self):
        server.enqueue({"url": "https://example.com/x"})
        self.assertTrue(server.QUEUE.wait_idle())
        report = server.queue_report()
        self.assertEqual(len(report["jobs"]), 1)
        self.assertIn("stopping", report)
        self.assertIn("pending", report)

    def test_rejects_a_request_with_no_url(self):
        with self.assertRaises(ValueError):
            server.enqueue({"url": "   "})
