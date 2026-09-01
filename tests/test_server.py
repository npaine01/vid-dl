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


class TestSubtitleModes(unittest.TestCase):
    def test_defaults_to_no_subtitles(self):
        job, command = server.prepare_download({"url": "u"}, ffmpeg="/x/ffmpeg")
        self.assertEqual(job.sub_mode, "none")
        self.assertNotIn("--write-subs", command)

    def test_sidecar_downloads_subtitles_without_encoding(self):
        job, command = server.prepare_download(
            {"url": "u", "sub_mode": "sidecar", "sub_lang": "ja"}, ffmpeg="/x/ffmpeg")
        self.assertEqual(job.sub_mode, "sidecar")
        self.assertIn("--write-subs", command)

    def test_burn_also_requests_the_subtitles_it_will_burn(self):
        job, command = server.prepare_download(
            {"url": "u", "sub_mode": "burn", "sub_lang": "ja", "sub_size": "large"},
            ffmpeg="/x/ffmpeg")
        self.assertEqual(job.sub_mode, "burn")
        self.assertEqual(job.sub_size, "large")
        self.assertIn("--write-subs", command)

    def test_refuses_burning_without_a_capable_ffmpeg(self):
        with self.assertRaises(ValueError) as caught:
            server.prepare_download(
                {"url": "u", "sub_mode": "burn", "sub_lang": "en"},
                ffmpeg="/x/ffmpeg", can_burn=False)
        self.assertIn("ffmpeg-full", str(caught.exception))

    def test_falls_back_to_sidecar_for_an_unknown_mode(self):
        job, _ = server.prepare_download(
            {"url": "u", "sub_mode": "interpretive-dance", "sub_lang": "en"},
            ffmpeg="/x/ffmpeg")
        self.assertEqual(job.sub_mode, "none")

    def test_audio_downloads_never_carry_a_subtitle_mode(self):
        job, _ = server.prepare_download(
            {"url": "u", "mode": "audio", "sub_mode": "burn", "sub_lang": "en"},
            ffmpeg="/x/ffmpeg")
        self.assertEqual(job.sub_mode, "none")


class TestBurnTargets(unittest.TestCase):
    def test_names_the_burned_copy_distinctly_beside_the_original(self):
        self.assertEqual(
            server.burned_path("/out/Some Clip.mp4"), "/out/Some Clip [subbed].mp4")

    def test_finds_the_subtitle_written_next_to_a_download(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "Clip.mp4").write_bytes(b"v")
            Path(folder, "Clip.ja.srt").write_text("1\n", encoding="utf-8")
            self.assertEqual(server.subtitle_beside(str(Path(folder, "Clip.mp4")), "ja"),
                             str(Path(folder, "Clip.ja.srt")))

    def test_returns_nothing_when_no_subtitle_was_written(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "Clip.mp4").write_bytes(b"v")
            self.assertIsNone(server.subtitle_beside(str(Path(folder, "Clip.mp4")), "ja"))


class TestSidecarRepair(unittest.TestCase):
    """Repair runs on every downloaded subtitle that looks like rolling ASR,
    keeping the untouched original alongside."""

    def setUp(self):
        import tempfile
        self.folder = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.folder.cleanup()

    def write(self, name, text):
        from pathlib import Path
        path = Path(self.folder.name, name)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_repairs_a_rolling_file_and_keeps_the_original(self):
        import fixtures
        from pathlib import Path
        lines = [f"line number {n}" for n in range(10)]
        path = self.write("Clip.en.srt", fixtures.rolling(lines))
        stats = server.repair_sidecar(path)

        self.assertTrue(stats["rolling"])
        self.assertTrue(Path(self.folder.name, "Clip.en.raw.srt").exists())
        import subs
        repaired = subs.parse(Path(path).read_text(encoding="utf-8"))
        self.assertEqual([c.lines[0] for c in repaired], lines)

    def test_leaves_authored_captions_completely_alone(self):
        import fixtures
        from pathlib import Path
        original = fixtures.authored([f"line {n}" for n in range(10)])
        path = self.write("Clip.en.srt", original)
        stats = server.repair_sidecar(path)

        self.assertFalse(stats["rolling"])
        self.assertFalse(Path(self.folder.name, "Clip.en.raw.srt").exists())
        self.assertEqual(Path(path).read_text(encoding="utf-8"), original)

    def test_converts_a_vtt_sidecar_to_srt(self):
        from pathlib import Path
        import fixtures
        lines = [f"line {n}" for n in range(10)]
        path = self.write("Clip.en.vtt",
                          "WEBVTT\n\n" + fixtures.rolling(lines))
        result = server.repair_sidecar(path)
        self.assertTrue(Path(self.folder.name, "Clip.en.srt").exists())
        self.assertEqual(result["path"], str(Path(self.folder.name, "Clip.en.srt")))


class TestBatchEnqueue(unittest.TestCase):
    def setUp(self):
        server.QUEUE = server.jobs.JobQueue(
            runner=lambda job: setattr(job, "status", "done")).start()

    def test_queues_every_selected_item_in_order(self):
        created = server.enqueue_many({
            "items": [{"url": "https://example.com/a", "title": "A"},
                      {"url": "https://example.com/b", "title": "B"}],
            "quality": "720",
        })
        self.assertEqual([job.title for job in created], ["A", "B"])
        self.assertEqual([job.quality for job in created], ["720", "720"])

    def test_applies_one_subtitle_choice_to_the_whole_batch(self):
        created = server.enqueue_many({
            "items": [{"url": "https://example.com/a"}, {"url": "https://example.com/b"}],
            "sub_mode": "sidecar", "sub_lang": "ja",
        })
        self.assertTrue(all(job.sub_lang == "ja" for job in created))
        self.assertTrue(all(job.sub_mode == "sidecar" for job in created))

    def test_rejects_a_batch_with_no_items(self):
        with self.assertRaises(ValueError):
            server.enqueue_many({"items": []})

    def test_skips_entries_without_a_url(self):
        created = server.enqueue_many({
            "items": [{"title": "no url"}, {"url": "https://example.com/b"}]})
        self.assertEqual(len(created), 1)
