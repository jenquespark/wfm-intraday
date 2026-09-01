"""Erlang C queueing model for contact centre staffing.

This module provides a self-contained, numerically stable Erlang C
implementation that depends only on the Python standard library (``math``).

The Erlang C formula gives the probability that an arriving call must wait
in the queue.  The service-level approximation used here is the standard
exponential tail approximation:

    P(wait > t) = Pw · exp(-(N − E) · t / AHT)

where:

    Pw   = Erlang C probability of waiting (all agents busy)
    N    = number of agents
    E    = offered load (Erlangs)
    AHT  = average handle time
    t    = service-level threshold

Reference:  Borst, Mandelbaum, & Reiman (2004) "Dimensioning Large Call
Centers" — Operations Research 52(1), 17–34.
"""

from __future__ import annotations

import logging
import math
from typing import Dict

logger = logging.getLogger(__name__)


def _erlang_b(offered_load: float, positions: int) -> float:
    """Recursive Erlang B formula (loss probability).

    ``B(E, 0) = 1``
    ``B(E, n) = E · B(E, n-1) / (E · B(E, n-1) + n)``

    Args:
        offered_load: Traffic intensity in Erlangs (>= 0).
        positions:    Number of servers / agents.

    Returns:
        Probability that all servers are busy (blocking probability).
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

    Uses the standard conversion from Erlang B:

        C(E, N) = N · B(E, N) / (N − E · (1 − B(E, N)))

    When ``N <= E`` the system is unstable; the function returns 1.0
    (certainty of waiting).

    Args:
        offered_load: Traffic intensity in Erlangs.
        positions:    Number of agents.

    Returns:
        Probability that a call waits, in [0, 1].
    """
    if positions <= 0:
        return 1.0
    if offered_load <= 0:
        return 0.0
    if positions <= offered_load:
        return 1.0  # unstable — will always wait

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
    """Exponential-tail approximation of ``P(wait <= threshold)``.

    ``P(wait <= t) = 1 − Pw · exp(−(N − E) · t / AHT)``

    Args:
        offered_load: Traffic intensity in Erlangs.
        positions:    Number of agents.
        aht_seconds:  Average handle time in seconds.
        threshold_seconds: Service-level threshold in seconds.

    Returns:
        Probability that wait time is within the threshold, in [0, 1].
    """
    if positions <= 0 or offered_load <= 0:
        return 1.0 if offered_load <= 0 else 0.0
    if positions <= offered_load:
        return 0.0  # unstable
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
    """Find the minimum number of agents needed to meet a service-level target.

    The search iterates N upward from the offered load until the target
    service level is reached or the occupancy ceiling is breached.

    Args:
        calls_per_interval: Number of calls arriving in the interval.
        aht_seconds:        Average handle time (seconds).
        interval_seconds:   Length of the interval (seconds).
        service_level_target:  Target fraction of calls answered within
            ``sl_threshold_seconds`` (default 0.80).
        sl_threshold_seconds:  Service-level threshold in seconds (default 20).
        max_occupancy:          Maximum agent occupancy (default 0.85).
            N is increased whenever occupancy exceeds this value.
        max_search:             Maximum positions to search (default 300).

    Returns:
        Dict with keys:
            * ``required_positions``  — minimum agents meeting SL target.
            * ``occupancy``           — achieved occupancy at that level.
            * ``service_level_achieved`` — achieved service level.
            * ``constrained_by_occupancy`` — True if the occupancy cap was
              the binding constraint.
    """
    if calls_per_interval <= 0 or aht_seconds <= 0:
        return {
            "required_positions": 0.0,
            "occupancy": 0.0,
            "service_level_achieved": 1.0,
            "constrained_by_occupancy": False,
        }

    offered_load = (calls_per_interval * aht_seconds) / interval_seconds

    # Lower bound: at least offered_load + 1, rounded up
    min_n = max(1, int(math.floor(offered_load + 1)))
    max_n = min_n + max_search

    best_n = min_n
    best_sl = 0.0
    constrained = False

    for n in range(min_n, max_n + 1):
        occ = offered_load / n
        if occ > max_occupancy:
            continue  # occupancy cap — need more agents

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
        "constrained_by_occupancy": bool(constrained or achieved_occupancy > max_occupancy),
    }


def chat_required_positions(
    chats_per_interval: float,
    aht_seconds: float,
    interval_seconds: float,
    concurrency: int = 3,
    occupancy_target: float = 0.85,
) -> Dict[str, float]:
    """Estimate chat staffing using a concurrency model.

    Chat differs from voice because one agent can handle multiple chats
    simultaneously.  The simple model used here is:

        required_agents = ceil(offered_concurrent_load / occupancy_target)

    where::

        offered_concurrent_load = (chats_per_interval * aht_seconds)
                                  / interval_seconds
                                  / concurrency

    This is deliberately simpler than Erlang C for voice because chat
    queueing behaviour is fundamentally different (parallel sessions).

    Args:
        chats_per_interval: Number of chats arriving in the interval.
        aht_seconds:        Average chat handling time (seconds).
        interval_seconds:   Interval length (seconds).
        concurrency:        Number of simultaneous chats per agent.
        occupancy_target:   Target occupancy fraction.

    Returns:
        Dict with keys ``required_positions`` and ``occupancy``.
    """
    if chats_per_interval <= 0 or aht_seconds <= 0:
        return {"required_positions": 0.0, "occupancy": 0.0}

    raw_load = (chats_per_interval * aht_seconds) / interval_seconds
    effective_load = raw_load / concurrency
    required = math.ceil(effective_load / occupancy_target) if effective_load > 0 else 0
    occupancy = effective_load / required if required > 0 else 0.0

    return {
        "required_positions": float(required),
        "occupancy": float(occupancy),
    }


def async_required_positions(
    items_per_interval: float,
    aht_seconds: float,
    service_hours_per_day: float,
    sla_business_days: float,
) -> Dict[str, float]:
    """Estimate back-office / async staffing using a workload model.

    Back-office work (email, processing) is not queueing in the Erlang
    sense — it is a throughput / capacity calculation:

        required_agents = ceil(volume_per_day * AHT / service_hours_per_day)

    The SLA window is expressed in business days and serves as a factual
    statement about the service expectation, not a queueing target.

    Args:
        items_per_interval: Items arriving in the interval.
        aht_seconds:        Average handling time per item (seconds).
        service_hours_per_day: Productive hours available per agent per day.
        sla_business_days:  Target processing window in business days.

    Returns:
        Dict with keys ``required_positions`` and ``occupancy``.
    """
    if items_per_interval <= 0 or aht_seconds <= 0:
        return {"required_positions": 0.0, "occupancy": 0.0}

    daily_volume = items_per_interval  # assumes interval is the unit of analysis
    daily_capacity = service_hours_per_day * 3600  # seconds
    required = math.ceil(daily_volume * aht_seconds / daily_capacity)
    occupancy = (daily_volume * aht_seconds) / (required * daily_capacity) if required > 0 else 0.0

    return {
        "required_positions": float(required),
        "occupancy": float(occupancy),
    }