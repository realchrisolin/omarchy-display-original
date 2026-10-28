#!/usr/bin/env python3
"""List Wi-Fi radios suitable for Miracast P2P and pick a default.

Preference order (auto):
  1. Supports P2P-GO
  2. No active NetworkManager STA connection (dedicated Miracast radio)
  3. Stable / predictable iface name as tie-break

When a second Wi‑Fi NIC is present and idle, auto-pick prefers it so
Miracast P2P is not time-sliced with home STA (avoids SCC tax on AX201).

Usage:
  ./scripts/list_p2p_radios.py
  ./scripts/list_p2p_radios.py --resolve
  ./scripts/list_p2p_radios.py --resolve --prefer wlan1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


def _run(cmd: list[str], timeout: float = 4.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _nm_wifi_states() -> dict[str, dict[str, str]]:
    """iface -> {state, connection} for wifi devices (not p2p-dev)."""
    out: dict[str, dict[str, str]] = {}
    try:
        r = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
    except Exception:
        return out
    for ln in (r.stdout or "").splitlines():
        parts = ln.split(":")
        if len(parts) < 4:
            continue
        dev, typ, state, conn = parts[0], parts[1], parts[2], ":".join(parts[3:])
        if typ != "wifi":
            continue
        if dev.startswith("p2p-"):
            continue
        out[dev] = {"state": state, "connection": conn if conn != "--" else ""}
    return out


def _phy_modes(phy: str) -> list[str]:
    try:
        r = _run(["iw", "phy", phy, "info"])
    except Exception:
        return []
    modes: list[str] = []
    in_modes = False
    for ln in (r.stdout or "").splitlines():
        if "Supported interface modes:" in ln:
            in_modes = True
            continue
        if not in_modes:
            continue
        stripped = ln.strip()
        if stripped.startswith("*"):
            modes.append(stripped[1:].strip())
            continue
        # End of modes block
        if stripped.startswith("Band ") or stripped.startswith("Supported commands"):
            break
        if stripped and not ln.startswith("\t") and not ln.startswith(" "):
            break
    return modes


def _ifaces_on_phy(phy: str) -> list[str]:
    found: list[str] = []
    net = Path("/sys/class/net")
    if not net.is_dir():
        return found
    for p in sorted(net.iterdir()):
        phy_link = p / "phy80211"
        if not phy_link.exists():
            continue
        try:
            name = os.path.basename(os.readlink(phy_link))
        except OSError:
            continue
        if name == phy:
            found.append(p.name)
    return found


def _phys() -> list[str]:
    phys: list[str] = []
    # Prefer /sys listing; fall back to iw phy
    phy_root = Path("/sys/class/ieee80211")
    if phy_root.is_dir():
        phys = sorted(p.name for p in phy_root.iterdir() if p.name.startswith("phy"))
    if phys:
        return phys
    try:
        r = _run(["iw", "phy"])
    except Exception:
        return []
    for ln in (r.stdout or "").splitlines():
        m = re.match(r"Wiphy\s+(\S+)", ln)
        if m:
            phys.append(m.group(1))
    return phys


def _driver_for_phy(phy: str) -> str:
    link = Path(f"/sys/class/ieee80211/{phy}/device/driver")
    try:
        return os.path.basename(os.readlink(link))
    except OSError:
        return ""


def _adapter_name(phy: str, driver: str) -> str:
    """Human adapter name from PCI/USB identity (any vendor — no hardcoding).

    PCI: text between class ``]:`` and the ``[vendor:device]`` id in ``lspci -nn``.
    USB: sysfs ``product`` (and optional ``manufacturer``) when present.
    """
    # PCI: parse lspci -nn for matching PCI_ID from uevent
    uevent = Path(f"/sys/class/ieee80211/{phy}/device/uevent")
    pci_id = ""
    try:
        for ln in uevent.read_text().splitlines():
            if ln.startswith("PCI_ID="):
                pci_id = ln.split("=", 1)[1].strip().lower()
                break
    except OSError:
        pass
    if pci_id and shutil.which("lspci"):
        try:
            out = _run(["lspci", "-nn"]).stdout or ""
        except Exception:
            out = ""
        # 8086:A0F0 in uevent → [8086:a0f0] in lspci
        needle = f"[{pci_id}]"
        for ln in out.splitlines():
            if needle.lower() not in ln.lower():
                continue
            # "… [0280]: <vendor string + product> [8086:a0f0] (rev 20)"
            m = re.search(
                r"\]:\s*(.+?)\s*" + re.escape(needle),
                ln,
                flags=re.IGNORECASE,
            )
            if m:
                name = m.group(1).strip()
                # Drop trailing revision only — keep full vendor/product as reported.
                name = re.sub(r"\s*\(rev\s+[^)]+\)\s*$", "", name, flags=re.IGNORECASE)
                if name:
                    return name
    # USB: manufacturer + product from sysfs when available
    dev = Path(f"/sys/class/ieee80211/{phy}/device")
    for base in (dev, dev / ".."):
        try:
            base = base.resolve()
        except OSError:
            continue
        manuf = prod = ""
        try:
            manuf = (base / "manufacturer").read_text().strip()
        except OSError:
            pass
        try:
            prod = (base / "product").read_text().strip()
        except OSError:
            pass
        if manuf and prod:
            return f"{manuf} {prod}"
        if prod:
            return prod
        if manuf:
            return manuf
    return driver or phy or "Wi-Fi"


def list_radios() -> list[dict[str, Any]]:
    nm = _nm_wifi_states()
    radios: list[dict[str, Any]] = []
    for phy in _phys():
        modes = _phy_modes(phy)
        p2p_go = "P2P-GO" in modes
        ifaces = _ifaces_on_phy(phy)
        # Prefer a managed (non-p2p) iface as the handle for this radio.
        managed = [i for i in ifaces if not i.startswith("p2p-")]
        if not managed:
            continue
        driver = _driver_for_phy(phy)
        adapter = _adapter_name(phy, driver)
        # One entry per managed iface (usually one).
        for iface in managed:
            nm_info = nm.get(iface, {})
            state = nm_info.get("state", "")
            conn = nm_info.get("connection", "")
            # "in use" = NM has an active connection (connected / connecting / …)
            in_use = bool(conn) or state.startswith("connected") or state in (
                "connecting",
                "preparing",
                "configuring",
                "ip-config",
                "ip-check",
                "secondaries",
                "activated",
            )
            # Also treat operstate up + default route as in use when NM sparse
            oper = ""
            try:
                oper = Path(f"/sys/class/net/{iface}/operstate").read_text().strip()
            except OSError:
                pass
            if not in_use and oper == "up" and conn:
                in_use = True
            label = iface
            bits = []
            if p2p_go:
                bits.append("P2P-GO")
            if in_use:
                # STA AP connection is normal (not "busy" in the Miracast sense).
                bits.append(("STA: " + conn) if conn else "STA")
            elif state:
                bits.append(state)
            if bits:
                label = f"{iface} ({', '.join(bits)})"
            radios.append(
                {
                    "iface": iface,
                    "phy": phy,
                    "driver": driver,
                    "adapterName": adapter,
                    "p2pGo": p2p_go,
                    "inUse": in_use,
                    "nmState": state,
                    "connection": conn,
                    "operstate": oper,
                    "modes": modes,
                    "label": label,
                }
            )
    return radios


def _is_usb_iface(name: str) -> bool:
    """udev USB wifi (…uN) or an iface name that contains 'usb'."""
    n = name or ""
    return bool(re.search(r"u[0-9]+$", n)) or "usb" in n.lower()


def parse_p2p_go_ifaces(iw_text: str) -> list[str]:
    """P2P-GO data ifaces from ``iw dev`` (not ``p2p-dev-*``)."""
    gos: list[str] = []
    iface = ""
    skip = False
    is_go = False
    for ln in (iw_text or "").splitlines():
        parts = ln.split()
        if len(parts) >= 2 and parts[0] == "Interface":
            if iface and is_go and not skip:
                gos.append(iface)
            iface = parts[1]
            skip = iface.startswith("p2p-dev-")
            is_go = False
            continue
        if skip or not iface:
            continue
        if len(parts) >= 2 and parts[0] == "type" and parts[1] == "P2P-GO":
            is_go = True
    if iface and is_go and not skip:
        gos.append(iface)
    return gos


def netdev_is_usb(iface: str, *, device_path: str = "", parent: str = "") -> bool:
    """True for udev USB wifi names or a sysfs device path under /usb."""
    if _is_usb_iface(iface) or _is_usb_iface(parent):
        return True
    return "/usb" in (device_path or "").lower()


def keep_bss_go_iface(
    go_ifaces: list[str],
    usb_ifaces: set[str],
    *,
    parent_of: Optional[Any] = None,
) -> str:
    """USB dedicated GO to keep across reconnect; empty for STA-shared leftover.

    AX201 leftover ``p2p-wlp0s20-0`` must not take keep-BSS: FluxCast then
    ``p2p_connect``s the live group and times out.
    """
    for go in go_ifaces:
        if not go:
            continue
        if go in usb_ifaces or netdev_is_usb(go):
            return go
        parent = ""
        if callable(parent_of):
            parent = str(parent_of(go) or "")
        if parent and (parent in usb_ifaces or netdev_is_usb(parent)):
            return go
    return ""


def _device_realpath(iface: str) -> str:
    try:
        return str((Path("/sys/class/net") / iface / "device").resolve())
    except OSError:
        return ""


def _parent_managed(iface: str) -> str:
    link = Path(f"/sys/class/net/{iface}/phy80211")
    try:
        phy = os.path.basename(os.readlink(link))
    except OSError:
        return ""
    for n in _ifaces_on_phy(phy):
        if not n.startswith("p2p-"):
            return n
    return ""


def live_usb_netdevs() -> set[str]:
    found: set[str] = set()
    net = Path("/sys/class/net")
    if not net.is_dir():
        return found
    for p in net.iterdir():
        parent = _parent_managed(p.name)
        if netdev_is_usb(
            p.name, device_path=_device_realpath(p.name), parent=parent
        ):
            found.add(p.name)
    return found


def live_keep_bss_go() -> str:
    try:
        text = _run(["iw", "dev"]).stdout or ""
    except Exception:
        text = ""
    return keep_bss_go_iface(
        parse_p2p_go_ifaces(text),
        live_usb_netdevs(),
        parent_of=_parent_managed,
    )


def _auto_pick(radios: list[dict[str, Any]]) -> Optional[str]:
    if not radios:
        return None
    go = [r for r in radios if r.get("p2pGo")]
    pool = go if go else radios
    idle = [r for r in pool if not r.get("inUse")]
    pool = idle if idle else pool
    return sorted(pool, key=score_radio, reverse=True)[0]["iface"]


def score_radio(r: dict[str, Any]) -> tuple:
    """Higher is better for auto-pick.

    Idle P2P-GO radios beat in-use STA radios so a second NIC can carry
    Miracast without sharing the home-Wi‑Fi radio (SCC / HT20 tax).
    """
    return (
        1 if r.get("p2pGo") else 0,
        # Strongly prefer not sharing with an active STA association.
        0 if r.get("inUse") else 2,
        # Prefer predictable names slightly (wlp* / wlan*)
        1 if re.match(r"^(wlan|wlp)\d", r.get("iface") or "") else 0,
        # Stable sort by iface name (lexicographic last in reverse sort)
        r.get("iface") or "",
    )


def resolve_iface(prefer: Optional[str] = None, radios: Optional[list[dict[str, Any]]] = None) -> Optional[str]:
    """Return a *live* iface: explicit prefer if present, else auto-pick.

    USB wifi names change on re-plug (…u4 → …u3). A missing prefer must not
    be returned — dedicated wpa then fails to exec. If the stale name looked
    like USB, pick a live USB P2P radio; otherwise auto among live radios.
    """
    radios = list(radios) if radios is not None else list_radios()
    prefer = (prefer or "").strip()
    if prefer and prefer.lower() not in ("auto", "default", ""):
        present = {r["iface"] for r in radios}
        if prefer in present:
            return prefer
        if _is_usb_iface(prefer):
            usb = [r for r in radios if _is_usb_iface(r.get("iface") or "")]
            return _auto_pick(usb) or _auto_pick(radios)
        return _auto_pick(radios)
    return _auto_pick(radios)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resolve", action="store_true", help="print only the resolved iface")
    ap.add_argument(
        "--keep-bss-go",
        action="store_true",
        help="print USB dedicated P2P-GO iface to keep on reconnect (empty if none)",
    )
    ap.add_argument("--prefer", default="", help="settings preference (auto or iface)")
    ap.add_argument("--json", action="store_true", default=True)
    args = ap.parse_args()
    if args.keep_bss_go:
        go = live_keep_bss_go()
        print(go or "")
        return 0 if go else 0
    radios = list_radios()
    resolved = resolve_iface(args.prefer or "auto", radios)
    if args.resolve:
        print(resolved or "")
        return 0 if resolved else 1
    payload = {
        "ok": True,
        "radios": radios,
        "prefer": args.prefer or "auto",
        "resolved": resolved,
    }
    print(json.dumps(payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
