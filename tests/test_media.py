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


class TestFindFfmpeg(unittest.TestCase):
    def test_finds_a_binary_at_a_known_location(self):
        with tempfile.TemporaryDirectory() as folder:
            path = make_executable(folder)
            self.assertEqual(
                media.find_ffmpeg(search_paths=[path], which=lambda n: None),
                path)

    def test_prefers_a_known_location_over_whatever_is_on_the_path(self):
        """Homebrew's ffmpeg-full is keg-only and never lands on PATH, but it
        is a superset of the slim formula, so it wins when both exist."""
        with tempfile.TemporaryDirectory() as folder:
            path = make_executable(folder)
            self.assertEqual(
                media.find_ffmpeg(search_paths=[path],
                                  which=lambda n: "/usr/bin/ffmpeg"),
                path)

    def test_falls_back_to_the_path(self):
        self.assertEqual(
            media.find_ffmpeg(search_paths=["/nonexistent/ffmpeg"],
                              which=lambda n: "/usr/bin/ffmpeg"),
            "/usr/bin/ffmpeg")

    def test_returns_none_when_ffmpeg_is_not_installed(self):
        self.assertIsNone(
            media.find_ffmpeg(search_paths=["/nonexistent/ffmpeg"],
                              which=lambda n: None))

    def test_ignores_a_known_path_that_is_not_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ffmpeg")
            open(path, "w").close()
            self.assertIsNone(
                media.find_ffmpeg(search_paths=[path], which=lambda n: None))
