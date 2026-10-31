#!/usr/bin/env python3
"""Unit tests for QVBR BitrateController (Smart View–aligned)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_path = Path(__file__).resolve().parent / "bitrate_controller.py"
_spec = importlib.util.spec_from_file_location("bitrate_controller", _path)
assert _spec and _spec.loader
bc = importlib.util.module_from_spec(_spec)
sys.modules["bitrate_controller"] = bc
_spec.loader.exec_module(bc)


class BitrateControllerTest(unittest.TestCase):
    def test_stall_can_go_below_smartview_min(self):
        cfg = bc.BitrateConfig()
        st = bc.BitrateState(kbps=2048, qp=25)
        d = bc.decide(
            st,
            bc.LinkSignals(tx_failed_delta=23, video_fps=30.0),
            cfg,
            cooldown_ok=True,
        )
        self.assertTrue(d.changed)
        self.assertLess(d.kbps, 2048)
        self.assertGreaterEqual(d.kbps, bc.STALL_MIN_KBPS)

    def test_stall_decreases(self):
        cfg = bc.BitrateConfig(init_kbps=10000, min_kbps=1500, max_kbps=15000)
        st = bc.BitrateState(kbps=10000, qp=22)
        d = bc.decide(
            st,
            bc.LinkSignals(video_fps=22.0),
            cfg,
            cooldown_ok=True,
        )
        self.assertTrue(d.changed)
        self.assertLess(d.kbps, 10000)
        self.assertIn("net_stall", d.reason)

    def test_retry_percent_does_not_demote(self):
        """iw retry% is not Smart View RR — must not invent LOSS."""
        cfg = bc.config_for_band(band_5ghz=True)
        st = bc.BitrateState(kbps=14000, qp=15)
        d = bc.decide(
            st,
            bc.LinkSignals(retry_percent=25.0, video_fps=60.0),
            cfg,
            cooldown_ok=True,
        )
        self.assertFalse(d.changed)
        self.assertEqual(d.kbps, 14000)
        self.assertEqual(d.qp, 15)

    def test_rtcp_loss_decreases(self):
        cfg = bc.BitrateConfig()
        st = bc.BitrateState(kbps=10000, qp=22)
        d = bc.decide(
            st,
            bc.LinkSignals(loss_fraction=0.05, video_fps=30.0),
            cfg,
            cooldown_ok=True,
        )
        self.assertTrue(d.changed)
        self.assertLess(d.kbps, 10000)
        self.assertIn("loss_rtcp", d.reason)

    def test_idr_burst_treated_as_stall(self):
        """Sink wfd_idr_request burst = decoder starved, not iw retry%."""
        cfg = bc.BitrateConfig()
        st = bc.BitrateState(kbps=10000, qp=22)
        d = bc.decide(
            st,
            bc.LinkSignals(idr_requests=5, video_fps=30.0),
            cfg,
            cooldown_ok=True,
        )
        self.assertTrue(d.changed)
        self.assertLess(d.kbps, 10000)
        self.assertIn("idr=", d.reason)
        ok, why = bc.should_apply_encode(
            applied_kbps=10000,
            applied_qp=22,
            desired_kbps=d.kbps,
            desired_qp=d.qp,
            reason=d.reason,
            now=20.0,
            last_apply_ts=12.0,
        )
        self.assertTrue(ok, why)
        self.assertTrue(why.startswith("urgent:"))

    def test_tx_failed_treated_as_stall(self):
        cfg = bc.BitrateConfig()
        st = bc.BitrateState(kbps=10000, qp=22)
        d = bc.decide(
            st,
            bc.LinkSignals(tx_failed_delta=3, video_fps=60.0),
            cfg,
            cooldown_ok=True,
        )
        self.assertTrue(d.changed)
        self.assertLess(d.kbps, 10000)
        self.assertIn("tx_failed", d.reason)

    def test_no_loss_increases_after_streak(self):
        cfg = bc.BitrateConfig(max_kbps=20000)
        st = bc.BitrateState(kbps=8000, qp=22, good_streak=0)
        for _ in range(3):
            d = bc.decide(
                st,
                bc.LinkSignals(video_fps=30.0, link_capacity_mbps=72.0),
                cfg,
                cooldown_ok=True,
            )
            st = bc.BitrateState(
                kbps=d.kbps,
                qp=d.qp,
                good_streak=d.good_streak,
                bad_streak=d.bad_streak,
                underfill_streak=d.underfill_streak,
            )
        self.assertTrue(d.changed)
        self.assertGreater(d.kbps, 8000)
        self.assertLessEqual(d.qp, 22)
        self.assertIn("no_loss_increase", d.reason)

    def test_qp_fill_when_under_55pct_of_setpoint(self):
        """Before the good>=3 recover tick, underfill still sharpens QP by 1."""
        cfg = bc.config_for_band(band_5ghz=True, width_mhz=20)
        ceiling = bc._clamp_kbps(10**9, cfg, 72.2)
        self.assertEqual(ceiling, bc.DEFAULT_MAX_KBPS)
        st = bc.BitrateState(kbps=ceiling, qp=22, good_streak=1, underfill_streak=1)
        d = bc.decide(
            st,
            bc.LinkSignals(
                video_fps=60.0,
                link_capacity_mbps=72.2,
                air_tx_mbps=5.0,
            ),
            cfg,
            cooldown_ok=True,
        )
        self.assertTrue(d.changed)
        self.assertEqual(d.kbps, ceiling)
        self.assertEqual(d.qp, 21)
        self.assertIn("qp_fill", d.reason)

    def test_qp_recover_from_stall_max(self):
        cfg = bc.config_for_band(band_5ghz=True, width_mhz=20)
        st = bc.BitrateState(kbps=5000, qp=44, good_streak=2)
        d = bc.decide(
            st,
            bc.LinkSignals(video_fps=60.0, link_capacity_mbps=72.2, air_tx_mbps=5.0),
            cfg,
            cooldown_ok=True,
        )
        self.assertTrue(d.changed)
        self.assertEqual(d.qp, 38)
        self.assertGreater(d.kbps, 5000)
        self.assertLessEqual(d.kbps, cfg.init_kbps)
        self.assertIn("qp_recover", d.reason)
        self.assertIn("no_loss_increase", d.reason)

    def test_qp_recover_at_ceiling(self):
        cfg = bc.config_for_band(band_5ghz=True, width_mhz=20)
        ceiling = bc._clamp_kbps(10**9, cfg, 72.2)
        st = bc.BitrateState(kbps=ceiling, qp=30, good_streak=2)
        d = bc.decide(
            st,
            bc.LinkSignals(video_fps=60.0, link_capacity_mbps=72.2, air_tx_mbps=12.0),
            cfg,
            cooldown_ok=True,
        )
        self.assertTrue(d.changed)
        self.assertEqual(d.kbps, ceiling)
        self.assertEqual(d.qp, 26)
        self.assertTrue(d.reason.startswith("qp_recover"))

    def test_qp_recover_step_sizes(self):
        cfg = bc.BitrateConfig()
        self.assertEqual(bc._qp_recover_step(44, cfg), 6)
        self.assertEqual(bc._qp_recover_step(36, cfg), 6)
        self.assertEqual(bc._qp_recover_step(35, cfg), 4)
        self.assertEqual(bc._qp_recover_step(28, cfg), 4)
        self.assertEqual(bc._qp_recover_step(27, cfg), 2)
        self.assertEqual(bc._qp_recover_step(16, cfg), 1)
        self.assertEqual(bc._qp_recover_step(15, cfg), 0)

    def test_qp_recover_applies_after_interval(self):
        ok, why = bc.should_apply_encode(
            applied_kbps=5000,
            applied_qp=44,
            desired_kbps=5000,
            desired_qp=38,
            reason="qp_recover qp44→38",
            now=150.0,
            last_apply_ts=90.0,
        )
        self.assertTrue(ok, why)
        self.assertIn("qp_recover", why)

    def test_qp_recover_last_step_applies(self):
        ok, why = bc.should_apply_encode(
            applied_kbps=14000,
            applied_qp=16,
            desired_kbps=14000,
            desired_qp=15,
            reason="qp_recover qp16→15",
            now=150.0,
            last_apply_ts=90.0,
        )
        self.assertTrue(ok, why)
        self.assertIn("qp_recover", why)

    def test_qp_plus_one_demote_still_held(self):
        ok, why = bc.should_apply_encode(
            applied_kbps=14000,
            applied_qp=22,
            desired_kbps=14000,
            desired_qp=23,
            reason="loss_rtcp:0.05",
            now=150.0,
            last_apply_ts=90.0,
        )
        self.assertFalse(ok)
        self.assertIn("qp_only", why)

    def test_samsung_1080p_ceiling(self):
        c5 = bc.config_for_band(band_5ghz=True, width_mhz=20)
        self.assertEqual(c5.min_kbps, 2_048)
        self.assertEqual(c5.init_kbps, 8_192)
        self.assertEqual(c5.max_kbps, 14_336)
        self.assertEqual(c5.qp_min, 15)
        self.assertEqual(c5.qp_max, 44)

    def test_kbps_roundtrip(self):
        self.assertEqual(bc.ffmpeg_to_kbps("10M"), 10000)
        self.assertEqual(bc.kbps_to_ffmpeg(10000), "10M")

    def test_stall_demote_applies_under_15pct(self):
        """2400→2048 (~14.7%) + Δqp=1 must apply on net_stall, not hold:urgent_small_delta."""
        ok, why = bc.should_apply_encode(
            applied_kbps=2400,
            applied_qp=24,
            desired_kbps=2048,
            desired_qp=25,
            reason="net_stall:tx_failed=6",
            now=20.0,
            last_apply_ts=0.0,
        )
        self.assertTrue(ok, why)
        self.assertTrue(why.startswith("urgent:"))

    def test_stall_demote_still_respects_urgent_cooldown(self):
        ok, why = bc.should_apply_encode(
            applied_kbps=2400,
            applied_qp=24,
            desired_kbps=2048,
            desired_qp=25,
            reason="net_stall:tx_failed=6",
            now=20.0,
            last_apply_ts=10.0,
        )
        self.assertFalse(ok)
        self.assertIn("urgent_cooldown", why)

    def test_coalesce_holds_qp_only(self):
        ok, reason = bc.should_apply_encode(
            applied_kbps=14000,
            applied_qp=22,
            desired_kbps=14000,
            desired_qp=21,
            reason="qp_fill:x",
            now=100.0,
            last_apply_ts=90.0,
        )
        self.assertFalse(ok)

    def test_fps_zero_is_not_air_stall(self):
        sig = bc.LinkSignals(stalled=False, video_fps=0.0, tx_failed_delta=0)
        self.assertFalse(bc._is_stall(sig))

    def test_fps_sag_is_air_stall(self):
        sig = bc.LinkSignals(stalled=False, video_fps=18.0)
        self.assertTrue(bc._is_stall(sig))

    def test_climb_10pct_applies_after_interval(self):
        """Samsung +10% (2300→2530) must apply; 15% gate used to block forever."""
        ok, why = bc.should_apply_encode(
            applied_kbps=2300,
            applied_qp=44,
            desired_kbps=2530,
            desired_qp=44,
            reason="no_loss_increase",
            now=150.0,
            last_apply_ts=90.0,
        )
        self.assertTrue(ok, why)
        self.assertIn("climb", why)

    def test_climb_10pct_holds_before_interval(self):
        ok, why = bc.should_apply_encode(
            applied_kbps=2300,
            applied_qp=44,
            desired_kbps=2530,
            desired_qp=44,
            reason="no_loss_increase",
            now=100.0,
            last_apply_ts=90.0,
        )
        self.assertFalse(ok)
        self.assertIn("min_interval", why)

    def test_unset_last_apply_does_not_wait_epoch(self):
        ok, why = bc.should_apply_encode(
            applied_kbps=2300,
            applied_qp=44,
            desired_kbps=2530,
            desired_qp=44,
            reason="no_loss_increase",
            now=1_793_147_165.0,
            last_apply_ts=0.0,
        )
        self.assertTrue(ok, why)
        self.assertNotIn("179", why)

    def test_idle_undershoot_keeps_1080p60(self):
        mode, streak = bc.abr_stream_mode(
            applied_kbps=2300,
            stream_mode="1920x1080p60",
            preferred_mode="1920x1080p60",
            low_streak=9,
        )
        self.assertEqual(mode, "1920x1080p60")
        self.assertEqual(streak, 0)

    def test_restore_preferred_1080p60_from_p30(self):
        mode, streak = bc.abr_stream_mode(
            applied_kbps=2300,
            stream_mode="1920x1080p30",
            preferred_mode="1920x1080p60",
            low_streak=0,
        )
        self.assertEqual(mode, "1920x1080p60")
        self.assertEqual(streak, 0)

    def test_leave_720p_and_30_preferred_alone(self):
        mode, _ = bc.abr_stream_mode(
            applied_kbps=1500,
            stream_mode="1280x720p60",
            preferred_mode="1280x720p60",
            low_streak=9,
        )
        self.assertEqual(mode, "1280x720p60")
        mode, _ = bc.abr_stream_mode(
            applied_kbps=1500,
            stream_mode="1920x1080p30",
            preferred_mode="1920x1080p30",
            low_streak=9,
        )
        self.assertEqual(mode, "1920x1080p30")

    def test_parse_stream_mode(self):
        self.assertEqual(bc.parse_stream_mode("1920x1080p60"), (1920, 1080, 60))
        self.assertEqual(bc.parse_stream_mode("1280x720p30"), (1280, 720, 30))
        self.assertEqual(bc.parse_stream_mode(""), (1920, 1080, 60))
        self.assertEqual(bc.parse_stream_mode("nope"), (1920, 1080, 60))

    def test_coalesce_applies_after_interval(self):
        ok, reason = bc.should_apply_encode(
            applied_kbps=8000,
            applied_qp=22,
            desired_kbps=14000,
            desired_qp=15,
            reason="no_loss_increase",
            now=150.0,
            last_apply_ts=90.0,
        )
        self.assertTrue(ok)
        self.assertIn("ready", reason)


if __name__ == "__main__":
    unittest.main()
