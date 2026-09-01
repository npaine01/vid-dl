"""Tests for media.py -- locating a usable ffmpeg."""
import os
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import media


def make_executable(folder, name="ffmpeg"):
    path = os.path.join(folder, name)
    with open(path, "w") as handle:
        handle.write("#!/bin/sh\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class TestRejectsBrokenBinaries(unittest.TestCase):
    """A binary can exist, be marked executable, and still fail to run --
    installing ffmpeg-full upgrades shared libraries that an older ffmpeg
    formula still links against, leaving a dyld failure behind."""

    def test_skips_a_binary_that_cannot_execute(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_executable(folder)
            self.assertIsNone(media.find_ffmpeg(
                search_paths=[path], which=lambda n: None,
                verify=lambda p: False))

    def test_falls_through_to_a_working_binary(self):
        with tempfile.TemporaryDirectory() as folder:
            broken = make_executable(folder, "ffmpeg")
            working = make_executable(folder, "ffmpeg2")
            self.assertEqual(
                media.find_ffmpeg(search_paths=[broken, working],
                                  which=lambda n: None,
                                  verify=lambda p: p == working),
                working)

    def test_rejects_a_broken_binary_found_on_the_path(self):
        self.assertIsNone(media.find_ffmpeg(
            search_paths=[], which=lambda n: "/usr/bin/ffmpeg",
            verify=lambda p: False))


class TestVerifyRuns(unittest.TestCase):
    def test_accepts_a_binary_that_reports_a_version(self):
        self.assertTrue(media.runs(sys.executable, args=("--version",),
                                   expect=""))

    def test_rejects_a_path_that_is_not_a_program(self):
        self.assertFalse(media.runs("/nonexistent/ffmpeg"))


class TestFindFfmpeg(unittest.TestCase):
    def test_finds_a_binary_at_a_known_location(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_executable(folder)
            self.assertEqual(
                media.find_ffmpeg(search_paths=[path], which=lambda n: None,
                                  verify=lambda p: True),
                path)

    def test_prefers_a_known_location_over_whatever_is_on_the_path(self):
        """Homebrew's ffmpeg-full is keg-only and never lands on PATH, but it
        is a superset of the slim formula, so it wins when both exist."""
        with tempfile.TemporaryDirectory() as folder:
            path = make_executable(folder)
            self.assertEqual(
                media.find_ffmpeg(search_paths=[path],
                                  which=lambda n: "/usr/bin/ffmpeg",
                                  verify=lambda p: True),
                path)

    def test_falls_back_to_the_path(self):
        with tempfile.TemporaryDirectory() as folder:
            on_path = make_executable(folder)
            self.assertEqual(
                media.find_ffmpeg(search_paths=["/nonexistent/ffmpeg"],
                                  which=lambda n: on_path,
                                  verify=lambda p: True),
                on_path)

    def test_returns_none_when_ffmpeg_is_not_installed(self):
        self.assertIsNone(
            media.find_ffmpeg(search_paths=["/nonexistent/ffmpeg"],
                              which=lambda n: None, verify=lambda p: True))

    def test_ignores_a_known_path_that_is_not_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ffmpeg")
            open(path, "w").close()
            self.assertIsNone(
                media.find_ffmpeg(search_paths=[path], which=lambda n: None,
                                  verify=lambda p: True))
