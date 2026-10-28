"""Pick a HEADLESS refresh the compositor can actually present.

Hyprland's headless backend typically advertises only 1920x1080@60Hz.
Forcing 30Hz on that output stalls ICC capture: wf-recorder defaults to
60fps pacing, ffmpeg IO goes flat, and FluxCast rebinds every ~12s
(first_capture_bytes 7–13s — the 5–10s Miracast input lag).
"""
from __future__ import annotations

import re
from typing import Iterable


_P_MODE = re.compile(r"(\d+)x(\d+)p(\d+)")
_AT_HZ = re.compile(r"@([0-9.]+)")


def fps_from_stream_mode(mode_id: str | None) -> int | None:
    m = _P_MODE.fullmatch(str(mode_id or "").strip())
    if not m:
        return None
    fps = int(m.group(3))
    return fps if fps > 0 else None


def advertised_hz(modes: Iterable) -> list[float]:
    """Parse hyprctl availableModes entries into refresh rates."""
    out: list[float] = []
    for item in modes or []:
        if isinstance(item, dict):
            raw = item.get("refreshRate") or item.get("refresh") or ""
            text = str(raw)
        else:
            text = str(item or "")
        hz = None
        m = _AT_HZ.search(text)
        if m:
            try:
                hz = float(m.group(1))
            except ValueError:
                hz = None
        elif text:
            try:
                hz = float(text.replace("Hz", "").strip())
            except ValueError:
                hz = None
        if hz and hz > 0:
            out.append(hz)
    return out


def pick_headless_refresh(want: int, advertised: Iterable[float], *, default: int = 60) -> int:
    """Return an advertised rate closest to want.

    If the output does not advertise ``want`` (typical: only 60Hz), use the
    closest advertised rate instead of inventing 30Hz.
    """
    try:
        want_n = int(want)
    except (TypeError, ValueError):
        want_n = int(default)
    if want_n < 1:
        want_n = int(default)
    rates = [float(r) for r in advertised if r and float(r) > 0]
    if not rates:
        rates = [float(default)]
    for rate in rates:
        if abs(rate - want_n) < 0.75:
            return int(round(rate))
    best = min(rates, key=lambda rate: abs(rate - want_n))
    return int(round(best))


def want_fps_from_state(modes: dict | None, settings: dict | None) -> int:
    """Prefer live RTSP current, then settings.streamMode, then fps/extendRefresh."""
    modes = modes if isinstance(modes, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    for mid in (str(modes.get("current") or ""), str(settings.get("streamMode") or "")):
        parsed = fps_from_stream_mode(mid)
        if parsed:
            return parsed
    for key in ("fps", "extendRefresh"):
        raw = settings.get(key)
        if raw in (None, ""):
            continue
        try:
            value = int(float(raw))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 60
