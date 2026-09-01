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


import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fixtures_for_jobs  # noqa: E402  (see tests/fixtures_for_jobs.py)


class TestRunBurn(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.srt = Path(self.folder.name, "Clip: A Film.en.srt")
        self.srt.write_text(fixtures_for_jobs.rolling_srt(), encoding="utf-8")
        self.video = str(Path(self.folder.name, "Clip: A Film.mp4"))
        Path(self.video).write_bytes(b"not really a video")
        self.output = str(Path(self.folder.name, "Clip [subbed].mp4"))

    def tearDown(self):
        self.folder.cleanup()

    def burn(self, spawn, **kwargs):
        job = jobs.Job(url="x")
        jobs.run_burn(job, ffmpeg="/x/ffmpeg", video=self.video,
                      subtitle=str(self.srt), output=self.output,
                      spawn=spawn, **kwargs)
        return job

    def test_stages_the_subtitle_under_a_name_safe_for_the_filtergraph(self):
        seen = {}

        def spawn(command, cwd=None):
            video_filter = command[command.index("-vf") + 1]
            name = video_filter.split("subtitles=")[1].split(":force_style")[0]
            seen["name"] = name
            seen["cwd"] = cwd
            # The workspace is torn down afterwards, so check it while it lives.
            seen["staged_exists"] = Path(cwd, name).exists()
            return FakeProcess([])

        self.burn(spawn)
        self.assertNotIn(":", seen["name"])
        self.assertNotIn(",", seen["name"])
        self.assertNotIn("/", seen["name"])
        self.assertIsNotNone(seen["cwd"])
        self.assertTrue(seen["staged_exists"])

    def test_repairs_rolling_captions_before_burning_them(self):
        staged = {}

        def spawn(command, cwd=None):
            name = command[command.index("-vf") + 1]
            name = name.split("subtitles=")[1].split(":force_style")[0]
            staged["text"] = Path(cwd, name).read_text(encoding="utf-8")
            return FakeProcess([])

        self.burn(spawn)
        self.assertNotIn("00:00:04,350 --> 00:00:04,360", staged["text"])
        self.assertEqual(staged["text"].count("first line"), 1)

    def test_marks_the_job_done_and_names_the_output(self):
        job = self.burn(lambda command, cwd=None: FakeProcess([]))
        self.assertEqual(job.status, "done")
        self.assertEqual(job.filename, "Clip [subbed].mp4")

    def test_tracks_progress_against_the_known_duration(self):
        job = jobs.Job(url="x")
        seen = []
        process = FakeProcess([])

        def lines():
            for line in ["out_time=00:00:15.000000", "out_time=00:00:30.000000"]:
                yield line
                seen.append(job.percent)

        process.stdout = lines()
        jobs.run_burn(job, ffmpeg="/x/ffmpeg", video=self.video,
                      subtitle=str(self.srt), output=self.output,
                      duration_ms=60000, spawn=lambda c, cwd=None: process)
        self.assertEqual(seen, [25.0, 50.0])
        self.assertEqual(job.percent, 100)   # completion overrides

    def test_reports_the_burning_stage_while_it_runs(self):
        seen = []

        def spawn(command, cwd=None):
            seen.append(jobs.Job.__dict__ and None)
            return FakeProcess([])

        job = jobs.Job(url="x")
        stages = []
        original = FakeProcess.wait

        def watching(self):
            stages.append(job.stage)
            return original(self)

        FakeProcess.wait = watching
        try:
            jobs.run_burn(job, ffmpeg="/x/ffmpeg", video=self.video,
                          subtitle=str(self.srt), output=self.output,
                          spawn=lambda c, cwd=None: FakeProcess([]))
        finally:
            FakeProcess.wait = original
        self.assertEqual(stages, ["burning"])

    def test_fails_the_job_when_the_font_is_unavailable(self):
        job = jobs.Job(url="x")
        jobs.run_burn(job, ffmpeg="/x/ffmpeg", video=self.video,
                      subtitle=str(self.srt), output=self.output,
                      language="ja", font_available=lambda name: False,
                      spawn=lambda c, cwd=None: FakeProcess([]))
        self.assertEqual(job.status, "error")
        self.assertIn("Hiragino Sans", job.error)

    def test_reports_an_encoder_failure(self):
        job = self.burn(lambda command, cwd=None:
                        FakeProcess(["Error initializing filter"], returncode=1))
        self.assertEqual(job.status, "error")


class TestBurnKeepsEarlierRepairStats(unittest.TestCase):
    """The sidecar is repaired once, before burning. run_burn repairs its own
    staged copy too, but that second pass sees an already-clean file -- so its
    stats must not replace the ones describing what actually changed."""

    def test_does_not_overwrite_stats_from_an_earlier_repair(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            srt = Path(folder, "Clip.en.srt")
            srt.write_text(fixtures_for_jobs.rolling_srt(), encoding="utf-8")
            video = Path(folder, "Clip.mp4")
            video.write_bytes(b"v")

            job = jobs.Job(url="x")
            job.subtitle_stats = {"rolling": True, "cues_in": 29, "cues_out": 15}
            jobs.run_burn(job, ffmpeg="/x/ffmpeg", video=str(video),
                          subtitle=str(srt), output=str(Path(folder, "out.mp4")),
                          spawn=lambda c, cwd=None: FakeProcess([]))
            self.assertEqual(job.subtitle_stats["cues_in"], 29)
            self.assertEqual(job.subtitle_stats["cues_out"], 15)

    def test_records_stats_when_nothing_repaired_it_earlier(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            srt = Path(folder, "Clip.en.srt")
            srt.write_text(fixtures_for_jobs.rolling_srt(), encoding="utf-8")
            video = Path(folder, "Clip.mp4")
            video.write_bytes(b"v")

            job = jobs.Job(url="x")
            jobs.run_burn(job, ffmpeg="/x/ffmpeg", video=str(video),
                          subtitle=str(srt), output=str(Path(folder, "out.mp4")),
                          spawn=lambda c, cwd=None: FakeProcess([]))
            self.assertTrue(job.subtitle_stats["rolling"])
