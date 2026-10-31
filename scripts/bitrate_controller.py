"""Samsung Smart View–style BitrateController (QVBR encode strategy only).

Derived from ``libremotedisplay_wfd.so`` + live dig (S23→hotyeah, 1080p)::

    BitrateController: init, min=2097152, init=8388608, max=14680064
    BitrateController: mMinQP=15, mMaxQP=44
    decideUDPBitrate(RTCP RR) / calculateFractionLost
    LOSS → decreaseUDPBitrate; No loss → increaseUDPBitrate
    updateBitrateByNetStall → aggressive decrease
    MediaCodec live setBitrate (we coalesce SIGUSR1 — VAAPI limitation)

**Not** used for ``encodeStrategy=performance`` (CQP ladder in
``dynamic_encode.py``).

Without sink RTCP, we do **not** invent LOSS from iw retry%%. Demote on
NetworkStall (fps/sender), hard tx_failed, or a sink WFD IDR burst
(decoder starvation). Climb init→max when healthy. QP fill toward the
encode setpoint so VAAPI QVBR actually spends bits (CAC-in-VBR).
CEA fps stays at the preferred M4 mode; idle QVBR undershoot is not a
reason to drop 1080p60→p30.

Pure functions / small state object — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Samsung BitrateController (live dig, resolution=2 / 1080p), values in kbps.
DEFAULT_INIT_KBPS = 8_192  # 8 * 1024
DEFAULT_MIN_KBPS = 2_048  # 2 * 1024
# Decoder starvation (IDR / tx_failed): keep a decodeable stream below Smart View min.
STALL_MIN_KBPS = 800
DEFAULT_MAX_KBPS = 14_336  # 14 * 1024
DEFAULT_QP_MIN = 15
DEFAULT_QP_MAX = 44
DEFAULT_QP = 22

# RTCP RR fraction lost (only when real RR is supplied — not iw retry%).
LOSS_FRACTION_HIGH = 0.02
LOSS_FRACTION_CLEAR = 0.005

DECREASE_FACTOR = 0.80
INCREASE_FACTOR = 1.10
# Below Samsung init, climb faster (still capped at init this step).
INCREASE_TOWARD_INIT_FACTOR = 1.25
STALL_DECREASE_FACTOR = 0.65

# Outer safety vs iw MCS (Samsung max ≪ MCS on HT20; rarely binds).
CAPACITY_FRAC = 0.75

# VAAPI QVBR under-fill → sharpen QP toward encode setpoint (not MCS fill).
FILL_LOW_FRAC = 0.55
QP_STEP = 1
QP_SHARPEN_STREAK = 2
# Stall recovery parks at qp_max (44). Healthy ticks must walk back to qmin
# with Δqp≥2 so coalesce actually SIGUSR1s (QP±1 is hold:qp_only).
QP_RECOVER_HI = 6  # qp ≥ 36 (stall floor)
QP_RECOVER_MID = 4  # qp ≥ 28
QP_RECOVER_LO = 2

# SIGUSR1 coalesce (VAAPI cannot live-setParameters).
APPLY_MIN_QP_DELTA = 2
APPLY_MIN_KBPS_FRAC = 0.15
# Samsung increaseUDPBitrate is 10%; 15% coalesce never let climbs apply.
APPLY_CLIMB_KBPS_FRAC = 0.08
APPLY_MIN_INTERVAL_S = 45.0
APPLY_FLUSH_INTERVAL_S = 120.0
APPLY_FLUSH_QP_DELTA = 2
APPLY_FLUSH_KBPS_FRAC = 0.15

# CEA fps is locked to the preferred M4 mode (Smart View). QVBR idle
# undershoot is not congestion — do not drop 1080p60→p30 on air fill.


@dataclass
class BitrateConfig:
    init_kbps: int = DEFAULT_INIT_KBPS
    min_kbps: int = DEFAULT_MIN_KBPS
    max_kbps: int = DEFAULT_MAX_KBPS
    qp_min: int = DEFAULT_QP_MIN
    qp_max: int = DEFAULT_QP_MAX
    rc_mode: str = "QVBR"


@dataclass
class BitrateState:
    kbps: int
    qp: int = DEFAULT_QP
    good_streak: int = 0
    bad_streak: int = 0
    underfill_streak: int = 0


@dataclass(frozen=True)
class LinkSignals:
    """Inputs analogous to Samsung RR + NetworkStall.

    ``retry_percent`` is accepted for API compat but **ignored** for LOSS —
    Smart View uses RTCP RR, not iw retries. Pass ``loss_fraction`` only when
    real RTCP RR is available.
    """

    loss_fraction: Optional[float] = None  # RTCP RR only
    stalled: bool = False
    video_fps: Optional[float] = None
    link_capacity_mbps: Optional[float] = None
    air_tx_mbps: Optional[float] = None
    tx_failed_delta: Optional[int] = None  # hard delivery fail
    retry_percent: Optional[float] = None  # ignored for demote (not Smart View)
    idr_requests: Optional[int] = None  # sink wfd_idr_request count this tick


@dataclass(frozen=True)
class BitrateDecision:
    kbps: int
    qp: int
    changed: bool
    reason: str
    qp_min: int
    qp_max: int
    rc_mode: str
    good_streak: int
    bad_streak: int
    underfill_streak: int


def config_for_band(
    *,
    band_5ghz: bool,
    width_mhz: Optional[float] = None,
) -> BitrateConfig:
    """Samsung BitrateController WLAN_BAND / resolution table (dig: 1080p)."""
    del width_mhz
    if band_5ghz:
        return BitrateConfig(
            init_kbps=DEFAULT_INIT_KBPS,
            min_kbps=DEFAULT_MIN_KBPS,
            max_kbps=DEFAULT_MAX_KBPS,
            qp_min=DEFAULT_QP_MIN,
            qp_max=DEFAULT_QP_MAX,
            rc_mode="QVBR",
        )
    return BitrateConfig(
        init_kbps=6_144,
        min_kbps=DEFAULT_MIN_KBPS,
        max_kbps=10_240,
        qp_min=DEFAULT_QP_MIN,
        qp_max=DEFAULT_QP_MAX,
        rc_mode="QVBR",
    )


def desired_fill_mbps(kbps: int, capacity_mbps: Optional[float]) -> float:
    """Air setpoint: min(encode target, CAPACITY_FRAC × MCS)."""
    target = max(0.0, float(kbps) / 1000.0)
    if capacity_mbps is not None and capacity_mbps > 1.0:
        return min(target, float(capacity_mbps) * CAPACITY_FRAC)
    return target


def _clamp_kbps(
    kbps: int,
    cfg: BitrateConfig,
    capacity_mbps: Optional[float],
    *,
    stall: bool = False,
) -> int:
    lo, hi = int(cfg.min_kbps), int(cfg.max_kbps)
    if stall:
        lo = min(lo, STALL_MIN_KBPS)
    if capacity_mbps is not None and capacity_mbps > 1.0:
        hi = min(hi, int(capacity_mbps * 1000 * CAPACITY_FRAC))
        hi = max(hi, lo)
    return max(lo, min(hi, int(kbps)))


def _clamp_qp(qp: int, cfg: BitrateConfig) -> int:
    return max(int(cfg.qp_min), min(int(cfg.qp_max), int(qp)))


def _qp_recover_step(qp: int, cfg: BitrateConfig) -> int:
    """Drop QP toward qmin. Bigger steps from stall-max so one apply is worth it."""
    span = int(qp) - int(cfg.qp_min)
    if span <= 0:
        return 0
    if qp >= 36:
        return min(QP_RECOVER_HI, span)
    if qp >= 28:
        return min(QP_RECOVER_MID, span)
    return min(QP_RECOVER_LO, span)


def _rtcp_loss_fraction(sig: LinkSignals) -> Optional[float]:
    """Real RTCP RR fraction lost only — never iw retry%."""
    if sig.loss_fraction is None:
        return None
    return max(0.0, min(1.0, float(sig.loss_fraction)))


def _is_stall(sig: LinkSignals) -> bool:
    """Air/decoder stall only. fps=0 is capture death (VIDEO_STALL rebind), not NetStall."""
    if sig.stalled:
        return True
    # Hard delivery failure (tx_failed) ≈ NetworkStall / path death.
    if sig.tx_failed_delta is not None and int(sig.tx_failed_delta) > 0:
        return True
    # Sink WFD IDR burst = decoder starved (not iw retry%).
    if sig.idr_requests is not None and int(sig.idr_requests) >= 2:
        return True
    if sig.video_fps is not None:
        v = float(sig.video_fps)
        # Sagging but still encoding. fps=0 / tiny fps is capture stall.
        if 5.0 <= v < 28.0:
            return True
    return False


def _decision(
    *,
    kbps: int,
    qp: int,
    changed: bool,
    reason: str,
    cfg: BitrateConfig,
    good: int,
    bad: int,
    underfill: int,
) -> BitrateDecision:
    return BitrateDecision(
        kbps=kbps,
        qp=_clamp_qp(qp, cfg),
        changed=changed,
        reason=reason,
        qp_min=cfg.qp_min,
        qp_max=cfg.qp_max,
        rc_mode=cfg.rc_mode,
        good_streak=good,
        bad_streak=bad,
        underfill_streak=underfill,
    )


def decide(
    state: BitrateState,
    sig: LinkSignals,
    cfg: BitrateConfig,
    *,
    cooldown_ok: bool,
) -> BitrateDecision:
    """QVBR strategy tick — Samsung table + RR/NetStall roles (no iw-retry LOSS)."""
    kbps = _clamp_kbps(state.kbps, cfg, sig.link_capacity_mbps)
    qp = _clamp_qp(getattr(state, "qp", DEFAULT_QP), cfg)
    good = int(state.good_streak)
    bad = int(state.bad_streak)
    underfill = int(getattr(state, "underfill_streak", 0) or 0)
    loss = _rtcp_loss_fraction(sig)
    stall = _is_stall(sig)
    fill = desired_fill_mbps(kbps, sig.link_capacity_mbps)
    air = sig.air_tx_mbps
    if air is not None and sig.link_capacity_mbps is not None:
        cap = float(sig.link_capacity_mbps)
        if cap > 1.0:
            air = min(float(air), cap)

    if not cooldown_ok:
        return _decision(
            kbps=kbps,
            qp=qp,
            changed=False,
            reason="hold:cooldown",
            cfg=cfg,
            good=good,
            bad=bad,
            underfill=underfill,
        )

    # NetworkStall / hard delivery — aggressive decrease (Samsung path).
    if stall:
        nxt = _clamp_kbps(
            int(kbps * STALL_DECREASE_FACTOR),
            cfg,
            sig.link_capacity_mbps,
            stall=True,
        )
        nqp = _clamp_qp(qp + QP_STEP, cfg)
        why = f"net_stall:fps={sig.video_fps}"
        if sig.tx_failed_delta and int(sig.tx_failed_delta) > 0:
            why = f"net_stall:tx_failed={sig.tx_failed_delta}"
        elif sig.idr_requests and int(sig.idr_requests) >= 2:
            why = f"net_stall:idr={sig.idr_requests}"
        return _decision(
            kbps=nxt,
            qp=nqp,
            changed=(nxt != kbps) or (nqp != qp),
            reason=why,
            cfg=cfg,
            good=0,
            bad=bad + 1,
            underfill=0,
        )

    # LOSS case — only real RTCP RR (Smart View). iw retry% is ignored.
    if loss is not None and loss >= LOSS_FRACTION_HIGH:
        nxt = _clamp_kbps(int(kbps * DECREASE_FACTOR), cfg, sig.link_capacity_mbps)
        nqp = _clamp_qp(qp + QP_STEP, cfg) if nxt < kbps else qp
        return _decision(
            kbps=nxt,
            qp=nqp,
            changed=(nxt != kbps) or (nqp != qp),
            reason=f"loss_rtcp:{loss:.3f}",
            cfg=cfg,
            good=0,
            bad=bad + 1,
            underfill=0,
        )

    clear = loss is None or loss < LOSS_FRACTION_CLEAR
    fps_ok = sig.video_fps is None or float(sig.video_fps) >= 29.0
    if not (clear and fps_ok):
        return _decision(
            kbps=kbps,
            qp=qp,
            changed=False,
            reason="hold:marginal",
            cfg=cfg,
            good=0,
            bad=bad,
            underfill=0,
        )

    good += 1

    # No-loss climb toward Samsung max (init → max), and walk QP off stall-max.
    at_ceiling = kbps >= _clamp_kbps(10**9, cfg, sig.link_capacity_mbps)
    if good >= 3:
        nxt = kbps
        if not at_ceiling:
            if kbps < int(cfg.init_kbps):
                toward = int(kbps * INCREASE_TOWARD_INIT_FACTOR)
                nxt = min(int(cfg.init_kbps), max(toward, int(kbps * INCREASE_FACTOR)))
            else:
                nxt = int(kbps * INCREASE_FACTOR)
            nxt = _clamp_kbps(nxt, cfg, sig.link_capacity_mbps)
        step = _qp_recover_step(qp, cfg)
        nqp = _clamp_qp(qp - step, cfg) if step else qp
        if nxt != kbps or nqp != qp:
            if nxt != kbps and nqp != qp:
                why = f"no_loss_increase+qp_recover qp{qp}→{nqp}"
            elif nqp != qp:
                why = f"qp_recover qp{qp}→{nqp}"
            else:
                why = "no_loss_increase"
            return _decision(
                kbps=nxt,
                qp=nqp,
                changed=True,
                reason=why,
                cfg=cfg,
                good=0,
                bad=0,
                underfill=0,
            )

    # VAAPI QVBR under-fill at setpoint → sharpen QP (CAC-in-VBR spend bits).
    if (
        air is not None
        and float(air) >= 2.0
        and fill >= 8.0
        and float(air) < fill * FILL_LOW_FRAC
        and qp > cfg.qp_min
    ):
        underfill += 1
        if underfill >= QP_SHARPEN_STREAK and good >= 2:
            nqp = _clamp_qp(qp - QP_STEP, cfg)
            return _decision(
                kbps=kbps,
                qp=nqp,
                changed=nqp != qp,
                reason=(
                    f"qp_fill:air={air:.1f}<{FILL_LOW_FRAC:.0%}×{fill:.1f}"
                    f" qp{qp}→{nqp}"
                ),
                cfg=cfg,
                good=0,
                bad=0,
                underfill=0,
            )
        return _decision(
            kbps=kbps,
            qp=qp,
            changed=False,
            reason=f"hold:underfill={underfill}/{QP_SHARPEN_STREAK}",
            cfg=cfg,
            good=good,
            bad=0,
            underfill=underfill,
        )

    if good < 3:
        return _decision(
            kbps=kbps,
            qp=qp,
            changed=False,
            reason=f"hold:good_streak={good}/3",
            cfg=cfg,
            good=good,
            bad=0,
            underfill=0,
        )

    return _decision(
        kbps=kbps,
        qp=qp,
        changed=False,
        reason="hold:at_ceiling_filled",
        cfg=cfg,
        good=good,
        bad=0,
        underfill=0,
    )


def is_urgent_apply(reason: str) -> bool:
    """Hard stalls may use a shorter coalesce window; RR loss does not."""
    return str(reason or "").startswith("net_stall:")


def urgent_interval_s(reason: str) -> float:
    """Decoder IDR storm needs a faster encode drop than tx_failed."""
    if "idr=" in str(reason or ""):
        return 8.0
    return min(30.0, APPLY_MIN_INTERVAL_S)


def should_apply_encode(
    *,
    applied_kbps: int,
    applied_qp: int,
    desired_kbps: int,
    desired_qp: int,
    reason: str,
    now: float,
    last_apply_ts: float,
) -> tuple[bool, str]:
    """Gate SIGUSR1 encode restarts while keeping decide() hot."""
    dq = abs(int(desired_qp) - int(applied_qp))
    base = max(1, int(applied_kbps))
    dfrac = abs(int(desired_kbps) - int(applied_kbps)) / float(base)
    raw_elapsed = float(now) - float(last_apply_ts or 0.0)
    first = not last_apply_ts or last_apply_ts <= 0.0
    # Wall-clock `now` minus unset last_apply_ts is ~epoch; don't print 1e9s waits.
    elapsed = 0.0 if first else max(0.0, raw_elapsed)
    climb = int(desired_kbps) > int(applied_kbps)

    if dq == 0 and dfrac < 0.01:
        return False, "hold:noop"

    recover = int(desired_qp) < int(applied_qp) and str(reason or "").startswith(
        "qp_recover"
    )
    # QP+1 demotes stay coalesced. QP recovery (toward qmin) may apply at Δqp=1
    # so the last step 16→15 is not stuck behind hold:qp_only.
    if dfrac < 0.01 and dq < APPLY_MIN_QP_DELTA and not recover:
        return (
            False,
            f"hold:qp_only Δqp={dq} (need ≥{APPLY_MIN_QP_DELTA})",
        )

    if is_urgent_apply(reason):
        urgent_interval = urgent_interval_s(reason)
        # Stall demotes must apply even when Δkbps is just under 15%
        # (2400→2048 is ~14.7% and Δqp=1). Climbs still use the 15%/Δqp≥2 gate.
        demote = int(desired_kbps) < int(applied_kbps)
        if demote or dq >= 1 or dfrac >= APPLY_MIN_KBPS_FRAC:
            if first or elapsed >= urgent_interval:
                return True, f"urgent:{reason}"
            return (
                False,
                f"hold:urgent_cooldown {elapsed:.0f}/{urgent_interval:.0f}s",
            )
        return False, f"hold:urgent_small_delta Δqp={dq} Δkbps={dfrac:.0%}"

    if recover and dq >= 1:
        if first or elapsed >= APPLY_MIN_INTERVAL_S:
            return (
                True,
                f"ready:qp_recover Δqp={dq} wait={elapsed:.0f}s",
            )
        return (
            False,
            f"hold:min_interval {elapsed:.0f}/{APPLY_MIN_INTERVAL_S:.0f}s "
            f"(qp_recover Δqp={dq})",
        )

    # 10% Samsung climbs must apply after the interval (15% gate blocked them).
    if climb and dfrac >= APPLY_CLIMB_KBPS_FRAC:
        if first or elapsed >= APPLY_MIN_INTERVAL_S:
            return (
                True,
                f"ready:climb Δqp={dq} Δkbps={dfrac:.0%} wait={elapsed:.0f}s",
            )
        return (
            False,
            f"hold:min_interval {elapsed:.0f}/{APPLY_MIN_INTERVAL_S:.0f}s "
            f"(climb Δkbps={dfrac:.0%})",
        )

    if dq >= APPLY_MIN_QP_DELTA or dfrac >= APPLY_MIN_KBPS_FRAC:
        if first or elapsed >= APPLY_MIN_INTERVAL_S:
            return (
                True,
                f"ready:Δqp={dq} Δkbps={dfrac:.0%} wait={elapsed:.0f}s",
            )
        return (
            False,
            f"hold:min_interval {elapsed:.0f}/{APPLY_MIN_INTERVAL_S:.0f}s "
            f"(Δqp={dq} Δkbps={dfrac:.0%})",
        )

    if (dq >= APPLY_FLUSH_QP_DELTA or dfrac >= APPLY_FLUSH_KBPS_FRAC) and (
        first or elapsed >= APPLY_FLUSH_INTERVAL_S
    ):
        return (
            True,
            f"flush:Δqp={dq} Δkbps={dfrac:.0%} wait={elapsed:.0f}s",
        )

    return (
        False,
        f"hold:coalesce Δqp={dq} Δkbps={dfrac:.0%} wait={elapsed:.0f}s",
    )


def parse_stream_mode(mode: str) -> tuple[int, int, int]:
    """'1920x1080p60' → (1920, 1080, 60). Defaults to 1080p60."""
    import re

    m = re.fullmatch(r"(\d+)x(\d+)p(\d+)", str(mode or "").strip())
    if not m:
        return 1920, 1080, 60
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def abr_stream_mode(
    *,
    applied_kbps: int,
    stream_mode: str,
    preferred_mode: str,
    low_streak: int,
) -> tuple[str, int]:
    """Keep preferred CEA fps. Smart View locks mode at M4.

    Bitrate/QP adapt on stall, IDR burst, and real RTCP loss. QVBR idle
    undershoot (cursor, bar) is not congestion, so air fill must not drop
    1080p60→p30. ``applied_kbps`` is accepted for API compat and ignored.
    If a previous air-fill heuristic left 1080p30 while preferred is 60,
    restore 60. User-preferred 30 fps is left alone.
    """
    del applied_kbps, low_streak
    w, h, cur_fps = parse_stream_mode(stream_mode)
    pw, ph, pref_fps = parse_stream_mode(preferred_mode or stream_mode)
    if pref_fps < 60 or max(h, ph) < 1080:
        return f"{w}x{h}p{cur_fps}", 0
    if cur_fps >= 60:
        return f"{w}x{h}p{cur_fps}", 0
    rw, rh = (pw, ph) if ph >= 1080 else (w, h)
    return f"{rw}x{rh}p60", 0


def kbps_to_ffmpeg(kbps: int) -> str:
    if kbps >= 1000:
        mbps = kbps / 1000.0
        if mbps >= 10:
            return f"{mbps:.0f}M"
        return f"{mbps:.1f}M"
    return f"{int(kbps)}k"


def ffmpeg_to_kbps(text: str) -> int:
    import re

    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*([KkMm])?\s*$", str(text or ""))
    if not m:
        return DEFAULT_INIT_KBPS
    v = float(m.group(1))
    u = (m.group(2) or "M").upper()
    if u == "K":
        return max(1, int(v))
    return max(1, int(v * 1000))
