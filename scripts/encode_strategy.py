#!/usr/bin/env python3
"""Encoding strategy: QVBR ABR (default) vs Performance CQP.

Orthogonal to RENDER ENGINE (`captureEncode`) and PRESET QUALITY (`encodeProfile`).

* ``smartview`` — QVBR + BitrateController (Samsung dig 2/8/14 Mbps, QP 15–44);
  prefer DMA-BUF via ``prepare_dmabuf_settings``; pipe only on true starve
  (air TX ≪ ~2.5 Mbps absolute).
* ``performance`` — DMA-BUF + CQP; Best uses the QP ladder, not set-bitrate QVBR.
"""

from __future__ import annotations

import re
from typing import Any, Optional

STRATEGIES = ("smartview", "performance")
DEFAULT_STRATEGY = "smartview"


def bitrate_to_mbps(text: Any) -> float:
    raw = str(text or "").strip()
    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*([KkMmGg])?", raw)
    if not m:
        return 0.0
    v = float(m.group(1))
    u = (m.group(2) or "M").upper()
    if u == "G":
        return v * 1000.0
    if u == "K":
        return v / 1000.0
    return v


# QVBR quality-first HRD (~2 s of peak). Intel QVBR underspends at 0.25 s.
QVBR_VBV_MULTIPLIER = 2.0
# 1.0 = I-frames same quantizer as P. CQP High's 1.3 coarsens IDR and leaked
# into QVBR via encodeProfileEffective=high.
QVBR_I_QFACTOR = "1.0"


def latency_first_vbv_multiplier(
    encode_mbps: float,
    air_mbps: float | None = None,
) -> float:
    """HRD window in seconds for CQP/CBR. QVBR uses QVBR_VBV_MULTIPLIER.

    Intel low-delay AVC is 0.25 s. Tight air (capacity < 2× encode) uses
    0.5 s.
    """
    enc = max(0.0, float(encode_mbps or 0.0))
    if air_mbps is not None and float(air_mbps) > 0 and enc > 0:
        headroom = float(air_mbps) / enc
        if headroom < 2.0:
            return 0.5
        if headroom < 4.0:
            return 0.35
        return 0.25
    if enc >= 2.0:
        return 0.25
    return 0.5

# Starve detector: true Intel DMA BRC death is ~0.5–3 Mbps absolute.
# Do NOT use "% of maxrate" — QVBR on quiet 1080p60 UI often sits at 4–8 Mbps
# with qp≈22 even when maxrate is 45M (pipe and DMA match).
STARVE_TARGET_MIN_MBPS = 8.0
STARVE_ABS_MBPS = 2.5
STARVE_TICKS = 3


def normalize_strategy(value: Any) -> str:
    raw = str(value or "").strip().lower()
    aliases = {
        "smartview": "smartview",
        "smart-view": "smartview",
        "sv": "smartview",
        "qvbr": "smartview",
        "default": "smartview",
        "performance": "performance",
        "perf": "performance",
        "cqp": "performance",
    }
    return aliases.get(raw, DEFAULT_STRATEGY if not raw else raw)


def is_valid_strategy(value: Any) -> bool:
    return normalize_strategy(value) in STRATEGIES


def uses_sv_abr(settings: dict[str, Any]) -> bool:
    """QVBR BitrateController path (Best + default encode strategy)."""
    strategy = normalize_strategy(settings.get("encodeStrategy"))
    profile = str(settings.get("encodeProfile") or "").strip().lower()
    return strategy == "smartview" and profile == "best"


def prepare_dmabuf_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Prefer DMA-BUF for the default QVBR encode strategy.

    Clears session pipe-fallback so a fresh cast retries DMA-BUF. Does not
    override an explicit engine pin (``encodeStrategyPinnedEngine``).
    """
    if not isinstance(settings, dict):
        raise TypeError("settings must be a dict")
    strat = normalize_strategy(settings.get("encodeStrategy"))
    settings["encodeStrategyFallback"] = ""
    if strat == "smartview":
        settings["vaapiIQfactor"] = QVBR_I_QFACTOR
    if strat == "smartview" and not settings.get("encodeStrategyPinnedEngine"):
        settings["captureEncode"] = "dmabuf"
        settings["vaapiRcMode"] = "QVBR"
        settings["encodeStrategyAbr"] = "sv"
        try:
            q = int(str(settings.get("vaapiQuality") or "3"))
        except ValueError:
            q = 3
        if q < 3 or q > 4:
            settings["vaapiQuality"] = "3"
        settings.setdefault("vaapiQp", 22)
        settings.setdefault("encodeQpMin", 15)
        settings.setdefault("encodeQpMax", 44)
        settings.setdefault("bitrate", "8M")
        settings.setdefault("vaapiBitrate", settings.get("bitrate") or "8M")
        if settings.get("encodeWfdBitrateMbps") is None:
            settings["encodeWfdBitrateMbps"] = 8.0
        settings["vaapiAsyncDepth"] = 1
        sm = str(settings.get("streamMode") or "")
        settings["vaapiGop"] = 30 if ("p30" in sm and "p60" not in sm) else 60
        settings["vbvMultiplier"] = f"{QVBR_VBV_MULTIPLIER:.1f}"
    return {
        "encodeStrategy": strat,
        "captureEncode": settings.get("captureEncode"),
        "encodeStrategyFallback": settings.get("encodeStrategyFallback") or "",
        "vaapiRcMode": settings.get("vaapiRcMode"),
    }


def apply_to_settings(
    settings: dict[str, Any],
    strategy: str,
    *,
    retarget_engine: bool = True,
) -> dict[str, Any]:
    """Mutate settings for the chosen strategy. Returns a small summary dict."""
    if not isinstance(settings, dict):
        raise TypeError("settings must be a dict")
    strat = normalize_strategy(strategy)
    if strat not in STRATEGIES:
        raise ValueError(f"unknown encodeStrategy {strategy!r}")

    settings["encodeStrategy"] = strat
    # Explicit strategy pick clears sticky fallback and engine pin so retarget applies.
    settings["encodeStrategyFallback"] = ""
    settings["encodeStrategyPinnedEngine"] = False

    if strat == "smartview":
        settings["vaapiRcMode"] = "QVBR"
        settings["vaapiAsyncDepth"] = 1
        # Pipe hang floor is quality≥3; DMA-BUF QVBR also needs a low quality
        # index (faster=higher starves bits — quality=7 delivered ~4 Mbps).
        try:
            q = int(str(settings.get("vaapiQuality") or "3"))
        except ValueError:
            q = 3
        if q < 3 or q > 4:
            settings["vaapiQuality"] = "3"
        if settings.get("encodeQpMin") is None:
            settings["encodeQpMin"] = 15
        if settings.get("encodeQpMax") is None:
            settings["encodeQpMax"] = 44
        if settings.get("vaapiQp") is None:
            settings["vaapiQp"] = 22
        if not str(settings.get("bitrate") or "").strip():
            settings["bitrate"] = "8M"
        if not str(settings.get("vaapiBitrate") or "").strip():
            settings["vaapiBitrate"] = settings.get("bitrate") or "8M"
        if settings.get("encodeWfdBitrateMbps") is None:
            settings["encodeWfdBitrateMbps"] = 8.0
        settings["vbvMultiplier"] = f"{QVBR_VBV_MULTIPLIER:.1f}"
        settings["vaapiIQfactor"] = QVBR_I_QFACTOR
        if retarget_engine and not settings.get("encodeStrategyPinnedEngine"):
            # Attempt DMA-BUF first; starve watchdog may flip to vaapi.
            settings["captureEncode"] = "dmabuf"
        settings["encodeStrategyAbr"] = "sv"
    else:
        # Performance: sharp CQP on DMA-BUF, no QVBR bitrate churn.
        settings["vaapiRcMode"] = "CQP"
        settings["vbvMultiplier"] = "0.5"
        if retarget_engine and not settings.get("encodeStrategyPinnedEngine"):
            settings["captureEncode"] = "dmabuf"
        settings["encodeStrategyAbr"] = "cqp_ladder"
        # Drop SV congestion ceilings so CQP presets own the knobs.
        settings.pop("encodeWfdBitrateMbps", None)
        settings.pop("encodeCongestionBitrateMbps", None)

    return {
        "encodeStrategy": strat,
        "captureEncode": settings.get("captureEncode"),
        "vaapiRcMode": settings.get("vaapiRcMode"),
        "encodeStrategyAbr": settings.get("encodeStrategyAbr"),
    }


def dmabuf_qvbr_starving(
    *,
    capture_path: Optional[str],
    rc_mode: Optional[str],
    strategy: Optional[str],
    air_tx_mbps: Optional[float],
    target_mbps: Optional[float],
    video_fps: Optional[float],
    streak: int,
) -> tuple[bool, int, str]:
    """Return (should_fallback, new_streak, reason).

    Counts consecutive ticks where DMA-BUF QVBR delivers ≪ target while fps is OK.
    """
    strat = normalize_strategy(strategy)
    path = str(capture_path or "").strip().lower()
    rc = str(rc_mode or "").strip().upper()
    if strat != "smartview" or path != "dmabuf" or rc not in ("QVBR", "VBR", "CBR"):
        return False, 0, "inactive"
    if target_mbps is None or air_tx_mbps is None:
        return False, 0, "no_samples"
    if float(target_mbps) < STARVE_TARGET_MIN_MBPS:
        return False, 0, "target_low"
    # Require known healthy fps so quiet UI / rebind does not false-trigger.
    if video_fps is None or not (28.0 <= float(video_fps) <= 120.0):
        return False, 0, "fps_unknown"
    if float(air_tx_mbps) < STARVE_ABS_MBPS:
        new_streak = int(streak) + 1
        if new_streak >= STARVE_TICKS:
            return (
                True,
                new_streak,
                f"starve:{air_tx_mbps:.2f}<{STARVE_ABS_MBPS}abs(target={target_mbps:.1f})",
            )
        return False, new_streak, f"streak:{new_streak}/{STARVE_TICKS}"
    return False, 0, "ok"
