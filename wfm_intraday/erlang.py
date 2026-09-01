"""Channel staffing models for contact centre workload.

voice / Erlang C  — queueing model with service-level constraint.
chat              — concurrency-aware throughput model.
async / back-office — workload/capacity model (EXPERIMENTAL in v0.2).

All implementations depend only on the Python standard library (``math``).
"""

from __future__ import annotations

import logging
import math
from typing import Dict

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# Erlang B / C  (voice)
# ════════════════════════════════════════════════════════════════════════════


def _erlang_b(offered_load: float, positions: int) -> float:
    """Recursive Erlang B formula (loss probability).

    B(E, 0) = 1
    B(E, n) = E · B(E, n−1) / (E · B(E, n−1) + n)
    """
    if offered_load < 0 or positions < 0:
        raise ValueError(
            f"offered_load ({offered_load}) and positions ({positions}) must be >= 0"
        )
    if positions == 0:
        return 1.0
    if offered_load == 0:
        return 0.0

    b = 1.0
    for n in range(1, positions + 1):
        b = offered_load * b / (offered_load * b + n)
    return b


def erlang_c_pw(offered_load: float, positions: int) -> float:
    """Erlang C probability of waiting (all agents busy).

    C(E, N) = N · B(E, N) / (N − E · (1 − B(E, N)))

    When N <= E the system is unstable; returns 1.0.
    """
    if positions <= 0:
        return 1.0
    if offered_load <= 0:
        return 0.0
    if positions <= offered_load:
        return 1.0

    eb = _erlang_b(offered_load, positions)
    denom = positions - offered_load * (1.0 - eb)
    if denom <= 0:
        return 1.0
    return positions * eb / denom


def service_level_probability(
    offered_load: float,
    positions: int,
    aht_seconds: float,
    threshold_seconds: float,
) -> float:
    """Exponential-tail approximation: P(wait <= t).

    P(wait <= t) = 1 − Pw · exp(−(N − E) · t / AHT)
    """
    if positions <= 0 or offered_load <= 0:
        return 1.0 if offered_load <= 0 else 0.0
    if positions <= offered_load:
        return 0.0
    if aht_seconds <= 0:
        return 1.0

    pw = erlang_c_pw(offered_load, positions)
    exponent = -(positions - offered_load) * threshold_seconds / aht_seconds
    p_wait_gt = pw * math.exp(exponent)
    return max(0.0, min(1.0, 1.0 - p_wait_gt))


def required_positions(
    calls_per_interval: float,
    aht_seconds: float,
    interval_seconds: float,
    service_level_target: float = 0.80,
    sl_threshold_seconds: float = 20.0,
    max_occupancy: float = 0.85,
    max_search: int = 300,
) -> Dict[str, float]:
    """Find minimum agents needed to meet a service-level target (voice/Erlang C).

    Returns:
        Dict with ``required_positions``, ``occupancy``,
        ``service_level_achieved``, ``constrained_by_occupancy``.
    """
    if calls_per_interval <= 0 or aht_seconds <= 0:
        return {
            "required_positions": 0.0,
            "occupancy": 0.0,
            "service_level_achieved": 1.0,
            "constrained_by_occupancy": False,
        }

    offered_load = (calls_per_interval * aht_seconds) / interval_seconds
    min_n = max(1, int(math.floor(offered_load + 1)))
    max_n = min_n + max_search

    best_n = min_n
    best_sl = 0.0
    constrained = False

    for n in range(min_n, max_n + 1):
        occ = offered_load / n
        if occ > max_occupancy:
            continue

        sl = service_level_probability(
            offered_load=offered_load,
            positions=n,
            aht_seconds=aht_seconds,
            threshold_seconds=sl_threshold_seconds,
        )
        best_n = n
        best_sl = sl

        if sl >= service_level_target:
            break
        if n == max_n:
            constrained = True

    achieved_occupancy = offered_load / best_n if best_n > 0 else 0.0

    return {
        "required_positions": float(best_n),
        "occupancy": float(achieved_occupancy),
        "service_level_achieved": float(max(0.0, min(1.0, best_sl))),
        "constrained_by_occupancy": bool(
            constrained or achieved_occupancy > max_occupancy
        ),
    }


# ════════════════════════════════════════════════════════════════════════════
# Chat (concurrency-aware)
# ════════════════════════════════════════════════════════════════════════════


def chat_required_positions(
    chats_per_interval: float,
    aht_seconds: float,
    interval_seconds: float,
    concurrency: int = 3,
    occupancy_target: float = 0.85,
) -> Dict[str, float]:
    """Estimate chat staffing using a concurrency model.

    One agent handles multiple chats simultaneously.  The model:

        effective_load = (chats * aht) / interval_seconds / concurrency
        required = ceil(effective_load / occupancy_target)

    This is deliberately simpler than Erlang C — chat queueing behaviour
    differs from voice because agents work on multiple sessions in parallel.

    Limitations:
        Does not model chat abandon rate, response-time targets, or
        customer wait-time distributions.  Suitable for capacity estimation,
        not for chat-specific SLA guarantees.
    """
    if chats_per_interval <= 0 or aht_seconds <= 0:
        return {"required_positions": 0.0, "occupancy": 0.0}

    raw_load = (chats_per_interval * aht_seconds) / interval_seconds
    effective_load = raw_load / concurrency
    required = (
        math.ceil(effective_load / occupancy_target) if effective_load > 0 else 0
    )
    occupancy = effective_load / required if required > 0 else 0.0

    return {
        "required_positions": float(required),
        "occupancy": float(occupancy),
    }


# ════════════════════════════════════════════════════════════════════════════
# Async / back-office  (EXPERIMENTAL — disabled by default in v0.2)
# ════════════════════════════════════════════════════════════════════════════


def async_required_positions(
    items_per_interval: float,
    aht_seconds: float,
    service_hours_per_day: float,
    sla_business_days: float,  # reserved for future use
) -> Dict[str, float]:
    """Estimate back-office staffing using a workload model.

    **EXPERIMENTAL in v0.2.**  The current implementation treats
    *items_per_interval* as a daily volume and applies a simple staffing
    ratio.  This is NOT correct for interval-level WFM analysis where each
    interval represents 15–30 minutes of data.

    The function is kept for backward compatibility but callers should
    prefer voice or chat models.  Async channel support is planned for a
    future release.

    If you need to use this function, understand the limitation: it divides
    *items_per_interval* by daily capacity, which conflates interval-level
    and daily-level concepts.  For correct interval-level staffing, multiply
    the item count to reflect the full day first.
    """
    if items_per_interval <= 0 or aht_seconds <= 0:
        return {"required_positions": 0.0, "occupancy": 0.0}

    # WARNING: items_per_interval is treated as daily volume — this is
    # incorrect for interval-level analysis.  See docstring above.
    daily_volume = items_per_interval
    daily_capacity = service_hours_per_day * 3600.0
    required = math.ceil(daily_volume * aht_seconds / daily_capacity)
    occupancy = (
        (daily_volume * aht_seconds) / (required * daily_capacity)
        if required > 0 else 0.0
    )

    return {
        "required_positions": float(required),
        "occupancy": float(occupancy),
    }