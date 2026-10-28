#!/usr/bin/env python3
"""Detect a Wi-Fi STA occupying the WFD P2P subnet 192.168.49.0/24.

Android phone hotspots (DIRECT-*-*) often use the same range as Wi-Fi Direct.
That clash breaks P2P DHCP and RTSP. Ethernet, docker, and VPN are logged only.

  ./scripts/p2p_subnet_clash.py --check
  ./scripts/p2p_subnet_clash.py --fix
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

WFD_P2P_SUBNET = ipaddress.ip_network("192.168.49.0/24")


def is_p2p_ifname(name: str) -> bool:
    return (name or "").lower().startswith("p2p")


def is_wifi_iface(ifname: str, sysfs_root: str | Path = "/sys/class/net") -> bool:
    p = Path(sysfs_root) / ifname
    return (p / "wireless").exists() or (p / "phy80211").exists()


def overlapping_addrs(
    ifaces: list[dict[str, Any]],
    subnet: ipaddress.IPv4Network | ipaddress.IPv6Network = WFD_P2P_SUBNET,
) -> list[dict[str, Any]]:
    """Non-P2P addresses that overlap the WFD P2P subnet."""
    hits: list[dict[str, Any]] = []
    for iface in ifaces:
        dev = str(iface.get("ifname") or "?")
        if is_p2p_ifname(dev):
            continue
        for addr in iface.get("addr_info") or []:
            if addr.get("family") != "inet":
                continue
            local, prefixlen = addr.get("local"), addr.get("prefixlen")
            if local is None or prefixlen is None:
                continue
            try:
                net = ipaddress.ip_network(f"{local}/{prefixlen}", strict=False)
            except ValueError:
                continue
            if net.overlaps(subnet):
                hits.append(
                    {"ifname": dev, "addr": str(local), "prefixlen": int(prefixlen)}
                )
    return hits


def classify_clashes(
    hits: list[dict[str, Any]],
    *,
    is_wifi: Callable[[str], bool],
) -> list[dict[str, Any]]:
    """Wi-Fi STA → disconnect; everything else → warn (leave up)."""
    out: list[dict[str, Any]] = []
    for hit in hits:
        action = "disconnect" if is_wifi(hit["ifname"]) else "warn"
        out.append({**hit, "action": action})
    return out


def _run_ip_addr() -> list[dict[str, Any]]:
    try:
        r = subprocess.run(
            ["ip", "-j", "addr"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    try:
        data = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def disconnect_wifi(ifname: str) -> bool:
    try:
        r = subprocess.run(
            ["nmcli", "device", "disconnect", ifname],
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(
            f"[miracast-ctl] P2P subnet clash: nmcli disconnect {ifname} failed: {exc}",
            flush=True,
        )
        return False
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        print(
            f"[miracast-ctl] P2P subnet clash: nmcli disconnect {ifname} "
            f"failed: {err or r.returncode}",
            flush=True,
        )
        return False
    return True


def format_clash_line(item: dict[str, Any], *, did_disconnect: bool | None = None) -> str:
    cidr = f"{item['addr']}/{item['prefixlen']}"
    ifname = item["ifname"]
    if item.get("action") == "disconnect":
        if did_disconnect is False:
            return (
                f"[miracast-ctl] P2P subnet clash: Wi-Fi STA {ifname} is "
                f"{cidr} on {WFD_P2P_SUBNET} (disconnect failed)"
            )
        return (
            f"[miracast-ctl] P2P subnet clash: Wi-Fi STA {ifname} is "
            f"{cidr} on {WFD_P2P_SUBNET}; disconnecting"
        )
    return (
        f"[miracast-ctl] P2P subnet clash: {ifname}={cidr} overlaps "
        f"{WFD_P2P_SUBNET} (not Wi-Fi STA; leaving it)"
    )


def apply_clashes(
    classified: list[dict[str, Any]],
    *,
    fix: bool,
    disconnect: Callable[[str], bool] = disconnect_wifi,
) -> int:
    """Print log lines. With fix=True, disconnect Wi-Fi STA clashes.

    Returns the number of Wi-Fi STA ifaces disconnected.
    """
    n = 0
    for item in classified:
        if item.get("action") == "disconnect" and fix:
            ok = disconnect(item["ifname"])
            print(format_clash_line(item, did_disconnect=ok), flush=True)
            if ok:
                n += 1
        else:
            print(format_clash_line(item), flush=True)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="print JSON clashes; do not change ifaces")
    g.add_argument("--fix", action="store_true", help="disconnect Wi-Fi STA on 192.168.49.0/24")
    args = ap.parse_args(argv)

    classified = classify_clashes(
        overlapping_addrs(_run_ip_addr()),
        is_wifi=is_wifi_iface,
    )
    if args.check:
        json.dump(classified, sys.stdout)
        sys.stdout.write("\n")
        return 0
    apply_clashes(classified, fix=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
