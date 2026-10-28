#!/usr/bin/env python3
"""Unit tests for HEADLESS refresh clamping."""
import unittest

from headless_refresh import (
    advertised_hz,
    fps_from_stream_mode,
    pick_headless_refresh,
    want_fps_from_state,
)


class HeadlessRefreshTests(unittest.TestCase):
    def test_stream_mode_fps(self):
        self.assertEqual(fps_from_stream_mode("1920x1080p30"), 30)
        self.assertEqual(fps_from_stream_mode("1920x1080p60"), 60)
        self.assertIsNone(fps_from_stream_mode(""))
        self.assertIsNone(fps_from_stream_mode("1920x1080"))

    def test_advertised_hypr_strings(self):
        self.assertEqual(
            advertised_hz(["1920x1080@60.00Hz"]),
            [60.0],
        )
        self.assertEqual(
            advertised_hz(["1920x1080@60.00Hz", "1920x1080@30.00Hz"]),
            [60.0, 30.0],
        )

    def test_clamp_30_to_advertised_60(self):
        self.assertEqual(pick_headless_refresh(30, [60.0]), 60)
        self.assertEqual(pick_headless_refresh(60, [60.0]), 60)

    def test_keep_30_when_advertised(self):
        self.assertEqual(pick_headless_refresh(30, [60.0, 30.0]), 30)

    def test_empty_advertised_defaults_60(self):
        self.assertEqual(pick_headless_refresh(30, []), 60)
        self.assertEqual(pick_headless_refresh(0, []), 60)

    def test_want_prefers_live_negotiated(self):
        self.assertEqual(
            want_fps_from_state(
                {"current": "1920x1080p60"},
                {"streamMode": "1920x1080p30", "fps": "30", "extendRefresh": 30},
            ),
            60,
        )
        self.assertEqual(
            want_fps_from_state({}, {"streamMode": "1920x1080p30"}),
            30,
        )
        self.assertEqual(want_fps_from_state({}, {}), 60)


if __name__ == "__main__":
    unittest.main()
