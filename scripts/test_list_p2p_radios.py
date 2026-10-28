#!/usr/bin/env python3
"""Unit tests for list_p2p_radios resolve scoring and adapter naming."""

from __future__ import annotations

import unittest
from unittest import mock

from list_p2p_radios import (
    _adapter_name,
    keep_bss_go_iface,
    parse_p2p_go_ifaces,
    resolve_iface,
)


class ResolveIfaceTest(unittest.TestCase):
    def test_prefers_idle_p2p_go(self):
        radios = [
            {"iface": "wlp0s20f3", "p2pGo": True, "inUse": True},
            {"iface": "wlan1", "p2pGo": True, "inUse": False},
            {"iface": "wlan0", "p2pGo": False, "inUse": False},
        ]
        self.assertEqual(resolve_iface("auto", radios), "wlan1")

    def test_idle_beats_busy_even_when_name_worse(self):
        # Strong idle preference (score weight 2) over wlp* name bonus.
        radios = [
            {"iface": "wlp0s20f3", "p2pGo": True, "inUse": True},
            {"iface": "wlx00aabbccddee", "p2pGo": True, "inUse": False},
        ]
        self.assertEqual(resolve_iface("auto", radios), "wlx00aabbccddee")

    def test_explicit_prefer(self):
        radios = [
            {"iface": "wlp0s20f3", "p2pGo": True, "inUse": True},
            {"iface": "wlan1", "p2pGo": True, "inUse": False},
        ]
        self.assertEqual(resolve_iface("wlp0s20f3", radios), "wlp0s20f3")

    def test_stale_usb_prefer_picks_live_usb(self):
        radios = [
            {"iface": "wlp0s20f3", "p2pGo": True, "inUse": True},
            {"iface": "wlp0s20f0u3", "p2pGo": True, "inUse": False},
        ]
        self.assertEqual(resolve_iface("wlp0s20f0u4", radios), "wlp0s20f0u3")

    def test_stale_non_usb_prefer_auto_picks_idle_go(self):
        radios = [
            {"iface": "wlp0s20f3", "p2pGo": True, "inUse": True},
            {"iface": "wlan1", "p2pGo": True, "inUse": False},
        ]
        self.assertEqual(resolve_iface("wlan0", radios), "wlan1")

    def test_fallback_to_busy_go(self):
        radios = [
            {"iface": "wlp0s20f3", "p2pGo": True, "inUse": True},
            {"iface": "wlan0", "p2pGo": False, "inUse": False},
        ]
        self.assertEqual(resolve_iface("auto", radios), "wlp0s20f3")

    def test_no_go_falls_back(self):
        radios = [
            {"iface": "wlan0", "p2pGo": False, "inUse": True},
            {"iface": "wlan1", "p2pGo": False, "inUse": False},
        ]
        self.assertEqual(resolve_iface("auto", radios), "wlan1")


class KeepBssGoTest(unittest.TestCase):
    def test_parse_ax201_go(self):
        iw = (
            "phy#0\n"
            "\tInterface p2p-wlp0s20-0\n"
            "\t\ttype P2P-GO\n"
            "\t\tssid DIRECT-dN\n"
            "\tInterface wlp0s20f3\n"
            "\t\ttype managed\n"
        )
        self.assertEqual(parse_p2p_go_ifaces(iw), ["p2p-wlp0s20-0"])

    def test_ax201_leftover_does_not_keep_bss(self):
        self.assertEqual(
            keep_bss_go_iface(["p2p-wlp0s20-0"], set(), parent_of=lambda _: "wlp0s20f3"),
            "",
        )

    def test_usb_named_go_keeps_bss(self):
        self.assertEqual(
            keep_bss_go_iface(
                ["p2p-wlp0s20f0u4-0"],
                {"wlp0s20f0u4", "p2p-wlp0s20f0u4-0"},
                parent_of=lambda _: "wlp0s20f0u4",
            ),
            "p2p-wlp0s20f0u4-0",
        )

    def test_dedicated_p2p0_on_usb_phy_keeps_bss(self):
        self.assertEqual(
            keep_bss_go_iface(
                ["p2p-0"],
                {"wlan1", "p2p-0"},
                parent_of=lambda _: "wlan1",
            ),
            "p2p-0",
        )

    def test_skip_p2p_dev(self):
        iw = "\tInterface p2p-dev-wlp0s20f3\n\t\ttype P2P-device\n"
        self.assertEqual(parse_p2p_go_ifaces(iw), [])


class AdapterNameTest(unittest.TestCase):
    def _patch_uevent(self, uevent: str):
        real_read = __import__("pathlib").Path.read_text

        def read_text(self, *a, **k):
            if str(self).endswith("uevent"):
                return uevent
            raise OSError("nope")

        return mock.patch.object(__import__("pathlib").Path, "read_text", read_text)

    def test_pci_name_keeps_full_vendor_string(self):
        lspci = (
            "00:14.3 Network controller [0280]: "
            "Intel Corporation Wi-Fi 6 AX201 [8086:a0f0] (rev 20)\n"
        )

        def fake_run(cmd, timeout=4.0):
            class R:
                stdout = lspci
                returncode = 0

            return R()

        with mock.patch("list_p2p_radios._run", side_effect=fake_run):
            with mock.patch("list_p2p_radios.shutil.which", return_value="/usr/bin/lspci"):
                with self._patch_uevent("DRIVER=iwlwifi\nPCI_ID=8086:A0F0\n"):
                    name = _adapter_name("phy0", "iwlwifi")
        self.assertEqual(name, "Intel Corporation Wi-Fi 6 AX201")

    def test_pci_other_vendor_no_hardcoded_rewrite(self):
        lspci = (
            "01:00.0 Network controller [0280]: "
            "Some Vendor Ltd. Fancy Card [10ec:1234] (rev 01)\n"
        )

        def fake_run(cmd, timeout=4.0):
            class R:
                stdout = lspci
                returncode = 0

            return R()

        with mock.patch("list_p2p_radios._run", side_effect=fake_run):
            with mock.patch("list_p2p_radios.shutil.which", return_value="/usr/bin/lspci"):
                with self._patch_uevent("DRIVER=rtw88\nPCI_ID=10EC:1234\n"):
                    name = _adapter_name("phy1", "rtw88")
        self.assertEqual(name, "Some Vendor Ltd. Fancy Card")


if __name__ == "__main__":
    unittest.main()
