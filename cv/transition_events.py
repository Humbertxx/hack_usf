"""Derive transition feed events from consecutive observations (Snowflake-gated frames only)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from cv.models import ActivityType, Observation

# Stable keys for dashboard consecutive-dedupe (see plan).
DEDUPE_EATING = "activity_eating"
DEDUPE_DRINKING = "activity_drinking"
DEDUPE_FALLEN = "fallen"


def collect_transition_events(
    prev: Optional[Observation],
    curr: Observation,
) -> List[Dict[str, Any]]:
    """
    Emit zero or more logical events for the live feed.

    Activities: edge-detected eating and drinking only (locomotion alerts removed
    as too noisy with MediaPipe at varied camera distances).

    Fallen is handled in main.py when ``fall_detected`` alert fires.
    """
    out: List[Dict[str, Any]] = []

    if curr.activity == ActivityType.EATING and (
        prev is None or prev.activity != ActivityType.EATING
    ):
        name = (curr.primary_display_name or "").strip() or "Loved one"
        out.append(
            {
                "dedupe_key": DEDUPE_EATING,
                "event_type": "eating",
                "headline": f"{name} is eating",
            }
        )

    if curr.activity == ActivityType.DRINKING and (
        prev is None or prev.activity != ActivityType.DRINKING
    ):
        name = (curr.primary_display_name or "").strip() or "Loved one"
        out.append(
            {
                "dedupe_key": DEDUPE_DRINKING,
                "event_type": "drinking",
                "headline": f"{name} is drinking water",
            }
        )

    return out
