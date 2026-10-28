#!/usr/bin/env python3
"""Unit tests for P2P subnet clash detection (192.168.49.0/24)."""

from __future__ import annotations

import unittest
from unittest import mock

from p2p_subnet_clash import (
    apply_clashes,
    classify_clashes,
    format_clash_line,
    is_p2p_ifname,
    overlapping_addrs,
)


def _iface(name: str, addr: str, prefix: int = 24) -> dict:
    return {
        "ifname": name,
        "addr_info": [{"family": "inet", "local": addr, "prefixlen": prefix}],
    }


class OverlapTest(unittest.TestCase):
    def test_skips_p2p_go(self):
        hits = overlapping_addrs(
            [_iface("p2p-wlp0s20-0", "192.168.49.1"), _iface("wlp0s20f3", "192.168.10.106")]
        )
        self.assertEqual(hits, [])

    def test_skips_p2p_dev(self):
        hits = overlapping_addrs([_iface("p2p-dev-wlp0s20f3", "192.168.49.1")])
        self.assertEqual(hits, [])

    def test_hotspot_sta_hits(self):
        hits = overlapping_addrs([_iface("wlp0s20f3", "192.168.49.64")])
        self.assertEqual(hits, [{"ifname": "wlp0s20f3", "addr": "192.168.49.64", "prefixlen": 24}])

    def test_chrisnet_no_hit(self):
        hits = overlapping_addrs([_iface("wlp0s20f3", "192.168.10.106")])
        self.assertEqual(hits, [])

    def test_docker_hit(self):
        hits = overlapping_addrs([_iface("docker0", "192.168.49.1")])
        self.assertEqual(hits[0]["ifname"], "docker0")

    def test_p2p_ifname(self):
        self.assertTrue(is_p2p_ifname("p2p-wlp0s20-0"))
        self.assertTrue(is_p2p_ifname("p2p-dev-wlan0"))
        self.assertFalse(is_p2p_ifname("wlp0s20f3"))
        self.assertFalse(is_p2p_ifname("docker0"))


class ClassifyTest(unittest.TestCase):
    def test_wifi_sta_disconnects_others_warn(self):
        wifi = {"wlp0s20f3"}
        hits = overlapping_addrs(
            [
                _iface("wlp0s20f3", "192.168.49.64"),
                _iface("docker0", "192.168.49.1"),
                _iface("enp0s13f0u1u4", "192.168.49.20"),
            ]
        )
        classified = classify_clashes(hits, is_wifi=lambda n: n in wifi)
        by_name = {c["ifname"]: c["action"] for c in classified}
        self.assertEqual(by_name["wlp0s20f3"], "disconnect")
        self.assertEqual(by_name["docker0"], "warn")
        self.assertEqual(by_name["enp0s13f0u1u4"], "warn")


class ApplyTest(unittest.TestCase):
    def test_fix_disconnects_only_wifi(self):
        classified = [
            {"ifname": "wlp0s20f3", "addr": "192.168.49.64", "prefixlen": 24, "action": "disconnect"},
            {"ifname": "docker0", "addr": "192.168.49.1", "prefixlen": 24, "action": "warn"},
        ]
        disconnected: list[str] = []

        def fake_disconnect(name: str) -> bool:
            disconnected.append(name)
            return True

        with mock.patch("builtins.print"):
            n = apply_clashes(classified, fix=True, disconnect=fake_disconnect)
        self.assertEqual(n, 1)
        self.assertEqual(disconnected, ["wlp0s20f3"])

    def test_check_does_not_disconnect(self):
        classified = [
            {"ifname": "wlp0s20f3", "addr": "192.168.49.64", "prefixlen": 24, "action": "disconnect"},
        ]
        disconnected: list[str] = []
        with mock.patch("builtins.print"):
            n = apply_clashes(
                classified, fix=False, disconnect=lambda n: disconnected.append(n) or True
            )
        self.assertEqual(n, 0)
        self.assertEqual(disconnected, [])

    def test_format_wifi_and_other(self):
        wifi = format_clash_line(
            {"ifname": "wlp0s20f3", "addr": "192.168.49.64", "prefixlen": 24, "action": "disconnect"}
        )
        other = format_clash_line(
            {"ifname": "docker0", "addr": "192.168.49.1", "prefixlen": 24, "action": "warn"}
        )
        self.assertIn("Wi-Fi STA wlp0s20f3", wifi)
        self.assertIn("disconnecting", wifi)
        self.assertIn("docker0=", other)
        self.assertIn("leaving it", other)


if __name__ == "__main__":
    unittest.main()
