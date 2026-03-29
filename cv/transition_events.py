"""Derive transition feed events from consecutive observations (Snowflake-gated frames only)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from cv.models import ActivityType, Observation, PoseType

# Stable keys for dashboard consecutive-dedupe (see plan).
DEDUPE_SIT_TO_WALK = "locomotion_sit_to_walk"
DEDUPE_WALK_TO_SIT = "locomotion_walk_to_sit"
DEDUPE_EATING = "activity_eating"
DEDUPE_DRINKING = "activity_drinking"
DEDUPE_FALLEN = "fallen"


def collect_transition_events(
    prev: Optional[Observation],
    curr: Observation,
) -> List[Dict[str, Any]]:
    """
    Emit zero or more logical events for the live feed.

    Locomotion: only sitting ↔ walking (not standing).
    Activities: edge-detected eating and drinking.
    Fallen is handled in main.py when ``fall_detected`` alert fires.
    """
    out: List[Dict[str, Any]] = []

    if prev is not None:
        if prev.pose == PoseType.SITTING and curr.pose == PoseType.WALKING:
            out.append(
                {
                    "dedupe_key": DEDUPE_SIT_TO_WALK,
                    "event_type": "locomotion",
                    "headline": "Started walking",
                }
            )
        elif prev.pose == PoseType.WALKING and curr.pose == PoseType.SITTING:
            out.append(
                {
                    "dedupe_key": DEDUPE_WALK_TO_SIT,
                    "event_type": "locomotion",
                    "headline": "Sat down",
                }
            )

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
                "headline": f"{name} is drinking",
            }
        )

    return out
