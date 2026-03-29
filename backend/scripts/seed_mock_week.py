from __future__ import annotations

import argparse
import os
import random
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
from snowflake.connector.pandas_tools import write_pandas

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.models import ActivityType, MotionLevel, PoseType, Severity
from backend.server.snowflake_client import (
    SnowflakeClient,
    _load_runtime_env,
    _normalize_objects_detected,
    _to_us_eastern_naive,
)

US_EASTERN = ZoneInfo("America/New_York")
DEFAULT_DAYS = 7
DEFAULT_SEED = 7
BLOCKED_TARGETS = {
    ("GRANDMA_MONITOR", "PUBLIC"),
}


@dataclass(frozen=True)
class SubjectProfile:
    person_id: str
    display_name: str


@dataclass(frozen=True)
class MockObservation:
    id: str
    observed_at: datetime
    primary_person_id: str
    primary_display_name: str
    pose: PoseType
    pose_confidence: float
    activity: ActivityType
    activity_confidence: float
    objects_detected: list[str]
    room_hint: str
    is_fall_risk: bool
    motion_level: MotionLevel
    minutes_since_last_seen: int
    frame_quality: float
    session_id: str
    identity_confidence: float
    frame_thumb_base64: str | None = None


@dataclass(frozen=True)
class MockAlert:
    id: str
    observation_id: str
    alert_type: str
    severity: Severity
    triggered_at: datetime
    quick_message: str
    acknowledged: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seed one week of mock RAW_OBSERVATIONS, ALERTS, and optional LIVE_EVENTS "
            "into a non-production Snowflake target."
        )
    )
    parser.add_argument("--database", help="Override SNOWFLAKE_DATABASE for this run.")
    parser.add_argument("--schema", help="Override SNOWFLAKE_SCHEMA for this run.")
    parser.add_argument("--warehouse", help="Override SNOWFLAKE_WAREHOUSE for this run.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="How many days to seed. Default: 7.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed for deterministic mock data.")
    parser.add_argument(
        "--session-label",
        default=f"mock-week-{datetime.now(US_EASTERN).strftime('%Y%m%d-%H%M%S')}",
        help="Prefix used in RAW_OBSERVATIONS.SESSION_ID so mock data is easy to identify.",
    )
    parser.add_argument(
        "--include-grandpa",
        action="store_true",
        help="Seed a second enrolled subject (Grandpa) in addition to Grandma.",
    )
    parser.add_argument(
        "--skip-live-events",
        action="store_true",
        help="Only seed RAW_OBSERVATIONS and ALERTS. Skip LIVE_EVENTS even if the table exists.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be inserted without writing to Snowflake.",
    )
    parser.add_argument(
        "--allow-production-target",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def apply_env_overrides(args: argparse.Namespace) -> tuple[str, str]:
    _load_runtime_env()

    database = (
        args.database
        or os.getenv("SNOWFLAKE_DATABASE_DEVELOPMENT")
        or os.getenv("SNOWFLAKE_DATABASE")
        or ""
    ).strip()
    schema = (args.schema or os.getenv("SNOWFLAKE_SCHEMA") or "PUBLIC").strip()

    # Make the effective target explicit for SnowflakeClient(), which reads the
    # standard env vars rather than the development-specific fallback.
    if database:
        os.environ["SNOWFLAKE_DATABASE"] = database
    os.environ["SNOWFLAKE_SCHEMA"] = schema
    if args.warehouse:
        os.environ["SNOWFLAKE_WAREHOUSE"] = args.warehouse

    return database, schema


def guard_non_production_target(database: str, schema: str, *, allow_override: bool) -> None:
    target = (database.upper(), schema.upper())
    if not database:
        raise SystemExit(
            "SNOWFLAKE_DATABASE is empty. Point this script at a sandbox database with "
            "--database or environment variables before running it."
        )
    if allow_override:
        return
    if target in BLOCKED_TARGETS:
        raise SystemExit(
            f"Refusing to seed {database}.{schema}. "
            "Use a non-production database such as GRANDMA_MONITOR_DEV."
        )


def build_mock_dataset(
    *,
    days: int,
    seed: int,
    session_label: str,
    include_grandpa: bool,
) -> tuple[list[MockObservation], list[MockAlert], list[dict]]:
    rng = random.Random(seed)
    subjects = [SubjectProfile(person_id="grandma", display_name="Grandma")]
    if include_grandpa:
        subjects.append(SubjectProfile(person_id="grandpa", display_name="Grandpa"))

    today_local = datetime.now(US_EASTERN).date()
    start_date = today_local - timedelta(days=max(days - 1, 0))

    observations: list[MockObservation] = []
    alerts: list[MockAlert] = []

    for day_offset in range(days):
        current_day = start_date + timedelta(days=day_offset)
        for subject in subjects:
            session_id = f"{session_label}-{subject.person_id}"
            observations.extend(
                build_day_schedule(
                    current_day=current_day,
                    subject=subject,
                    rng=rng,
                    session_id=session_id,
                    day_offset=day_offset,
                )
            )

    # Dev-focused alerts for UI and live-event testing.
    for obs in observations:
        local_dt = obs.observed_at.astimezone(US_EASTERN)
        if obs.is_fall_risk:
            alerts.append(
                MockAlert(
                    id=str(uuid.uuid4()),
                    observation_id=obs.id,
                    alert_type="fall_detected",
                    severity=Severity.CRITICAL,
                    triggered_at=obs.observed_at + timedelta(minutes=1),
                    quick_message=f"Possible fall detected for {obs.primary_display_name}.",
                )
            )
        elif local_dt.weekday() == 2 and local_dt.hour == 20 and obs.primary_person_id == "grandma":
            alerts.append(
                MockAlert(
                    id=str(uuid.uuid4()),
                    observation_id=obs.id,
                    alert_type="no_motion",
                    severity=Severity.WARNING,
                    triggered_at=obs.observed_at + timedelta(minutes=12),
                    quick_message=f"{obs.primary_display_name} has been unusually still this evening.",
                )
            )

    live_events = build_live_events(observations, alerts)
    return observations, alerts, live_events


def build_day_schedule(
    *,
    current_day: date,
    subject: SubjectProfile,
    rng: random.Random,
    session_id: str,
    day_offset: int,
) -> list[MockObservation]:
    def obs_at(
        hour: int,
        minute: int,
        *,
        pose: PoseType,
        activity: ActivityType,
        room_hint: str,
        objects: list[str],
        motion_level: MotionLevel,
        is_fall_risk: bool = False,
    ) -> MockObservation:
        dt_local = make_local_dt(current_day, hour, minute, rng)
        return MockObservation(
            id=str(uuid.uuid4()),
            observed_at=dt_local,
            primary_person_id=subject.person_id,
            primary_display_name=subject.display_name,
            pose=pose,
            pose_confidence=round(rng.uniform(0.86, 0.98), 2),
            activity=activity,
            activity_confidence=round(rng.uniform(0.8, 0.97), 2),
            objects_detected=objects,
            room_hint=room_hint,
            is_fall_risk=is_fall_risk,
            motion_level=motion_level,
            minutes_since_last_seen=0,
            frame_quality=round(rng.uniform(0.82, 0.97), 2),
            session_id=session_id,
            identity_confidence=round(rng.uniform(0.88, 0.98), 2),
        )

    rows = [
        obs_at(
            7,
            35,
            pose=PoseType.STANDING,
            activity=ActivityType.IDLE,
            room_hint="bedroom",
            objects=["lamp", "dresser"],
            motion_level=MotionLevel.LOW,
        ),
        obs_at(
            8,
            15,
            pose=PoseType.SITTING,
            activity=ActivityType.EATING,
            room_hint="kitchen",
            objects=["plate", "mug", "table"],
            motion_level=MotionLevel.LOW,
        ),
        obs_at(
            10,
            40,
            pose=PoseType.SITTING,
            activity=ActivityType.DRINKING,
            room_hint="living_room",
            objects=["glass", "remote"],
            motion_level=MotionLevel.LOW,
        ),
        obs_at(
            12,
            35,
            pose=PoseType.SITTING,
            activity=ActivityType.EATING,
            room_hint="kitchen",
            objects=["plate", "water_glass"],
            motion_level=MotionLevel.LOW,
        ),
        obs_at(
            15,
            10,
            pose=PoseType.WALKING,
            activity=ActivityType.IDLE,
            room_hint="hallway",
            objects=["walker"],
            motion_level=MotionLevel.NORMAL,
        ),
        obs_at(
            18,
            20,
            pose=PoseType.SITTING,
            activity=ActivityType.EATING,
            room_hint="kitchen",
            objects=["plate", "fork", "water_glass"],
            motion_level=MotionLevel.LOW,
        ),
        obs_at(
            20,
            5,
            pose=PoseType.SITTING,
            activity=ActivityType.IDLE,
            room_hint="living_room",
            objects=["tv", "remote"],
            motion_level=MotionLevel.LOW,
        ),
    ]

    # Create snack rows by adding a second meal-window eating observation on alternating days.
    if day_offset % 2 == 0:
        rows.append(
            obs_at(
                16,
                10,
                pose=PoseType.SITTING,
                activity=ActivityType.EATING,
                room_hint="living_room",
                objects=["tea", "apple"],
                motion_level=MotionLevel.LOW,
            )
        )

    # Two fall-risk observations over the seeded week for live-event and alert testing.
    if day_offset in {2, 5} and subject.person_id == "grandma":
        rows.append(
            obs_at(
                21,
                35,
                pose=PoseType.LYING,
                activity=ActivityType.IDLE,
                room_hint="hallway",
                objects=["walker", "floor_mat"],
                motion_level=MotionLevel.NONE,
                is_fall_risk=True,
            )
        )

    return sorted(rows, key=lambda item: item.observed_at)


def make_local_dt(current_day: date, hour: int, minute: int, rng: random.Random) -> datetime:
    jitter = rng.randint(-8, 8)
    dt = datetime(
        current_day.year,
        current_day.month,
        current_day.day,
        hour,
        minute,
        tzinfo=US_EASTERN,
    )
    return dt + timedelta(minutes=jitter)


def build_live_events(observations: Iterable[MockObservation], alerts: Iterable[MockAlert]) -> list[dict]:
    by_observation_id = {obs.id: obs for obs in observations}
    first_meal_window_seen: set[tuple[str, date, str]] = set()
    events: list[dict] = []

    for obs in sorted(observations, key=lambda item: item.observed_at):
        if obs.activity != ActivityType.EATING:
            continue
        local_dt = obs.observed_at.astimezone(US_EASTERN)
        base_window = meal_window(local_dt)
        partition_key = (obs.primary_person_id, local_dt.date(), base_window)
        meal_kind = base_window if partition_key not in first_meal_window_seen else "snack"
        first_meal_window_seen.add(partition_key)
        events.append(
            live_event_row(
                observation=obs,
                event_type="eating",
                meal_kind=meal_kind,
                summary=(
                    f"{obs.primary_display_name} was observed having {meal_kind} in the {obs.room_hint.replace('_', ' ')}. "
                    "This is mock development data for UI and pipeline testing."
                ),
            )
        )

    for alert in alerts:
        if alert.alert_type != "fall_detected":
            continue
        obs = by_observation_id.get(alert.observation_id)
        if obs is None:
            continue
        events.append(
            live_event_row(
                observation=obs,
                event_type="fall_detected",
                meal_kind=None,
                summary=(
                    f"Possible fall detected for {obs.primary_display_name}. "
                    "This row was generated by the mock seeding script for non-production testing."
                ),
            )
        )

    return sorted(events, key=lambda item: item["OBSERVED_AT"])


def meal_window(local_dt: datetime) -> str:
    hhmm = (local_dt.hour, local_dt.minute)
    if hhmm < (12, 0):
        return "breakfast"
    if hhmm < (17, 30):
        return "lunch"
    return "dinner"


def live_event_row(
    *,
    observation: MockObservation,
    event_type: str,
    meal_kind: str | None,
    summary: str,
) -> dict:
    if event_type == "fall_detected":
        headline = f"{observation.primary_display_name}: possible fall detected"
    elif meal_kind:
        headline = f"{observation.primary_display_name} — {meal_kind.title()}"
    else:
        headline = "Update from home monitoring"

    created_at = _to_us_eastern_naive(observation.observed_at + timedelta(minutes=2))
    return {
        "ID": str(uuid.uuid4()),
        "OBSERVATION_ID": observation.id,
        "PRIMARY_PERSON_ID": observation.primary_person_id,
        "PRIMARY_DISPLAY_NAME": observation.primary_display_name,
        "EVENT_TYPE": event_type,
        "OBSERVED_AT": _to_us_eastern_naive(observation.observed_at),
        "CREATED_AT": created_at,
        "MEAL_KIND": meal_kind,
        "HEADLINE": headline,
        "SUMMARY": summary,
    }


def raw_observation_rows(observations: Iterable[MockObservation]) -> list[dict]:
    return [
        {
            "ID": obs.id,
            "OBSERVED_AT": _to_us_eastern_naive(obs.observed_at),
            "INSERTED_AT": _to_us_eastern_naive(obs.observed_at + timedelta(minutes=1)),
            "PERSON_DETECTED": True,
            "PRIMARY_PERSON_ID": obs.primary_person_id,
            "PRIMARY_DISPLAY_NAME": obs.primary_display_name,
            "IDENTITY_CONFIDENCE": obs.identity_confidence,
            "POSE": obs.pose.value,
            "POSE_CONFIDENCE": obs.pose_confidence,
            "ACTIVITY": obs.activity.value,
            "ACTIVITY_CONFIDENCE": obs.activity_confidence,
            "OBJECTS_DETECTED": _normalize_objects_detected(obs.objects_detected),
            "ROOM_HINT": obs.room_hint,
            "IS_FALL_RISK": obs.is_fall_risk,
            "MOTION_LEVEL": obs.motion_level.value,
            "MINUTES_SINCE_LAST_SEEN": obs.minutes_since_last_seen,
            "FRAME_QUALITY": obs.frame_quality,
            "SESSION_ID": obs.session_id,
            "FRAME_THUMB_BASE64": obs.frame_thumb_base64,
        }
        for obs in observations
    ]


def alert_rows(alerts: Iterable[MockAlert]) -> list[dict]:
    return [
        {
            "ID": alert.id,
            "OBSERVATION_ID": alert.observation_id,
            "ALERT_TYPE": alert.alert_type,
            "SEVERITY": alert.severity.value,
            "TRIGGERED_AT": _to_us_eastern_naive(alert.triggered_at),
            "INSERTED_AT": _to_us_eastern_naive(alert.triggered_at + timedelta(minutes=1)),
            "QUICK_MESSAGE": alert.quick_message,
            "ACKNOWLEDGED": alert.acknowledged,
        }
        for alert in alerts
    ]


def table_exists(conn, table_name: str) -> bool:
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = CURRENT_SCHEMA()
              AND TABLE_NAME = %s
            """,
            (table_name.upper(),),
        )
        return bool(cursor.fetchone()[0])
    finally:
        cursor.close()


def current_target(conn) -> tuple[str, str, str]:
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_WAREHOUSE()")
        database, schema, warehouse = cursor.fetchone()
        return str(database), str(schema), str(warehouse)
    finally:
        cursor.close()


def write_rows(conn, table_name: str, rows: list[dict]) -> int:
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    result = write_pandas(
        conn,
        df,
        table_name,
        auto_create_table=False,
        use_logical_type=True,
    )
    if isinstance(result, tuple) and len(result) >= 3:
        ok, inserted = bool(result[0]), int(result[2])
    elif isinstance(result, tuple) and len(result) == 2:
        ok, inserted = bool(result[0]), int(result[1])
    else:
        ok, inserted = bool(result), len(rows)
    if not ok:
        raise RuntimeError(f"write_pandas returned success=False for {table_name}")
    return inserted


def print_plan(
    *,
    database: str,
    schema: str,
    session_label: str,
    observations: list[MockObservation],
    alerts: list[MockAlert],
    live_events: list[dict],
    include_live_events: bool,
) -> None:
    start_at = min(obs.observed_at for obs in observations).astimezone(US_EASTERN)
    end_at = max(obs.observed_at for obs in observations).astimezone(US_EASTERN)
    print(f"Target: {database}.{schema}")
    print(f"Session label: {session_label}")
    print(f"Observations: {len(observations)}")
    print(f"Alerts: {len(alerts)}")
    print(f"Live events: {len(live_events) if include_live_events else 0} ({'enabled' if include_live_events else 'skipped'})")
    print(f"Time span: {start_at.isoformat()} -> {end_at.isoformat()}")
    print("Cleanup SQL:")
    print(cleanup_sql(session_label))


def cleanup_sql(session_label: str) -> str:
    escaped = session_label.replace("'", "''")
    return (
        "DELETE FROM LIVE_EVENTS WHERE OBSERVATION_ID IN "
        f"(SELECT ID FROM RAW_OBSERVATIONS WHERE SESSION_ID LIKE '{escaped}%');\n"
        "DELETE FROM ALERTS WHERE OBSERVATION_ID IN "
        f"(SELECT ID FROM RAW_OBSERVATIONS WHERE SESSION_ID LIKE '{escaped}%');\n"
        f"DELETE FROM RAW_OBSERVATIONS WHERE SESSION_ID LIKE '{escaped}%';"
    )


def main() -> None:
    args = parse_args()
    database, schema = apply_env_overrides(args)
    guard_non_production_target(
        database,
        schema,
        allow_override=args.allow_production_target,
    )

    observations, alerts, live_events = build_mock_dataset(
        days=args.days,
        seed=args.seed,
        session_label=args.session_label,
        include_grandpa=args.include_grandpa,
    )

    print_plan(
        database=database,
        schema=schema,
        session_label=args.session_label,
        observations=observations,
        alerts=alerts,
        live_events=live_events,
        include_live_events=not args.skip_live_events,
    )

    if args.dry_run:
        print("Dry run complete. No Snowflake writes were performed.")
        return

    client = SnowflakeClient()
    try:
        current_database, current_schema, current_warehouse = current_target(client.conn)
        guard_non_production_target(
            current_database,
            current_schema,
            allow_override=args.allow_production_target,
        )
        print(f"Connected to {current_database}.{current_schema} via {current_warehouse}")

        if not table_exists(client.conn, "RAW_OBSERVATIONS"):
            raise RuntimeError("RAW_OBSERVATIONS does not exist on the target schema.")
        if not table_exists(client.conn, "ALERTS"):
            raise RuntimeError("ALERTS does not exist on the target schema.")

        inserted_observations = write_rows(client.conn, "RAW_OBSERVATIONS", raw_observation_rows(observations))
        inserted_alerts = write_rows(client.conn, "ALERTS", alert_rows(alerts))
        print(f"Inserted {inserted_observations} RAW_OBSERVATIONS rows")
        print(f"Inserted {inserted_alerts} ALERTS rows")

        if args.skip_live_events:
            print("Skipped LIVE_EVENTS seeding by request.")
        elif table_exists(client.conn, "LIVE_EVENTS"):
            inserted_live_events = write_rows(client.conn, "LIVE_EVENTS", live_events)
            print(f"Inserted {inserted_live_events} LIVE_EVENTS rows")
        else:
            print("LIVE_EVENTS table not found. Skipped LIVE_EVENTS seeding.")

        print("Mock week seeding complete.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
