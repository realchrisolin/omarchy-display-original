#!/usr/bin/env python3
"""Unit tests for link-watch soft-TX / fps stall gating."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = ROOT / "scripts" / "miracast_link_watch.py"


def _load():
    spec = importlib.util.spec_from_file_location("miracast_link_watch", MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class LinkWatchStallGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_video_fps_healthy(self):
        self.assertTrue(self.m._video_fps_healthy(30.0))
        self.assertTrue(self.m._video_fps_healthy(20.0))
        self.assertFalse(self.m._video_fps_healthy(19.9))
        self.assertFalse(self.m._video_fps_healthy(None))

    def test_waydroid_soft_tx_not_stall(self):
        # ~2 Mbps at 30 fps must not count as stall (CQP quiet UI).
        self.assertFalse(
            self.m._soft_tx_counts_as_stall(2.0, 30.0, stall_mbps=3.0)
        )
        self.assertFalse(
            self.m._soft_tx_counts_as_stall(1.9, 30.0, stall_mbps=3.0)
        )

    def test_soft_tx_with_dead_fps_is_stall(self):
        # Rebind-unknown band (<15) — must not soft-stall.
        self.assertFalse(
            self.m._soft_tx_counts_as_stall(2.0, 5.0, stall_mbps=3.0)
        )
        self.assertFalse(
            self.m._soft_tx_counts_as_stall(2.0, 10.6, stall_mbps=3.0)
        )
        # Truly soft fps (below healthy, above unknown band) still stalls.
        self.assertTrue(
            self.m._soft_tx_counts_as_stall(2.0, 16.0, stall_mbps=3.0)
        )
        # AAC: no video_frames (fps=None). Moving TX is not a stall.
        self.assertFalse(
            self.m._soft_tx_counts_as_stall(2.0, None, stall_mbps=3.0)
        )
        self.assertFalse(
            self.m._soft_tx_counts_as_stall(1.3, None, stall_mbps=3.0)
        )

    def test_near_zero_tx_is_stall(self):
        self.assertTrue(
            self.m._soft_tx_counts_as_stall(0.05, 30.0, stall_mbps=3.0)
        )
        self.assertTrue(
            self.m._soft_tx_counts_as_stall(0.05, None, stall_mbps=3.0)
        )

    def test_recent_video_fps_from_log(self):
        text = "\n".join(
            [
                "2026-09-16T03:46:01-0400 [FluxCast WFD Media] Sender health: "
                "tx+100 KiB; video_frames=100 audio_frames=10",
                "2026-09-16T03:46:06-0400 [FluxCast WFD Media] Sender health: "
                "tx+200 KiB; video_frames=250 audio_frames=20",
            ]
        )
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "cast.log"
            log.write_text(text)
            fps = self.m._recent_video_fps(log)
        self.assertIsNotNone(fps)
        # 150 frames / 5 s = 30 fps
        self.assertAlmostEqual(fps, 30.0, places=1)

    def test_video_stall_ignores_link_watch_echo(self):
        echo = (
            "[link-watch] VIDEO_STALL in cast.log "
            "(FluxCast handles rebind; link-watch not double-restarting)\n"
        )
        self.assertFalse(self.m._video_stall_logged(echo))
        real = "2026-10-27T21:00:00 [FluxCast WFD Media] VIDEO_STALL — rebind\n"
        self.assertTrue(self.m._video_stall_logged(real))
        self.assertTrue(self.m._video_stall_logged(echo + real))


class P2pIfaceParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load()

    def test_go_preferred_over_device(self):
        text = """
phy#0
	Interface p2p-dev-wlp0s20
		addr aa:bb:cc:dd:ee:ff
		type P2P-device
	Interface p2p-wlp0s20-20
		addr aa:bb:cc:dd:ee:00
		type P2P-GO
	Interface wlp0s20f3
		addr aa:bb:cc:dd:ee:ff
		type managed
"""
        rows = self.m._p2p_data_ifaces_from_iw(text)
        self.assertEqual(rows, [("p2p-wlp0s20-20", "P2P-GO")])

    def test_client_group(self):
        text = """
	Interface p2p-wlp0s20-8
		type P2P-client
	Interface p2p-dev-wlp0s20
		type P2P-device
"""
        rows = self.m._p2p_data_ifaces_from_iw(text)
        self.assertEqual(rows, [("p2p-wlp0s20-8", "P2P-client")])

    def test_empty_dump_peer_left_only_on_go(self):
        self.assertTrue(
            self.m._empty_station_dump_means_peer_left("P2P-GO", "")
        )
        self.assertTrue(
            self.m._empty_station_dump_means_peer_left("P2P-GO", "  \n")
        )
        self.assertFalse(
            self.m._empty_station_dump_means_peer_left("P2P-client", "")
        )
        self.assertFalse(
            self.m._empty_station_dump_means_peer_left(
                "P2P-GO",
                "Station aa:bb:cc:dd:ee:ff\n\tinactive time:\t10 ms\n",
            )
        )


if __name__ == "__main__":
    unittest.main()
