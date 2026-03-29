import os
import uuid
from datetime import datetime, timezone

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1])) # REMEMBER TO DELETE !!

from server.snowflake_client import SnowflakeClient
from models import Observation, Alert, PoseType, ActivityType, MotionLevel, Severity


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")  # allow quoted values
        if key and key not in os.environ:
            os.environ[key] = value


# Load env vars from backend/.env.humberto or backend/.env if present
repo_root = Path(__file__).resolve().parents[1]
_load_env_file(repo_root / ".env.humberto")
_load_env_file(repo_root / ".env")

missing = [k for k in ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"] if not os.getenv(k)]
if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

def generate_mock_observation():
    return Observation(
        id=str(uuid.uuid4()),
        observed_at=datetime.now(timezone.utc),
        person_detected=True,
        pose=PoseType.SITTING,
        pose_confidence=0.92,
        activity=ActivityType.WATCHING_TV,
        activity_confidence=0.85,
        objects_detected=["remote", "couch"],
        room_hint="living_room",
        is_fall_risk=False,
        motion_level=MotionLevel.LOW,
        minutes_since_last_seen=0,
        frame_quality=0.88,
        session_id="test-session-001"
    )

def generate_mock_alert(observation_id: str):
    return Alert(
        id=str(uuid.uuid4()),
        observation_id=observation_id,
        alert_type="no_motion",
        severity=Severity.WARNING,
        triggered_at=datetime.now(timezone.utc),
        quick_message="No movement detected for 35 minutes."
    )

# Test
client = SnowflakeClient()

# Insert 15 observations (triggers flush at 10)
for i in range(15):
    obs = generate_mock_observation()
    client.add_observation(obs)
    print(f"Added observation {i+1}")

# Insert an alert
obs = generate_mock_observation()
client.add_observation(obs)
alert = generate_mock_alert(obs.id)
client.add_alert(alert)
created_alert_id = alert.id

# Final flush
client.flush()

# Verify
print("\nRecent observations:")
for obs in client.get_recent_observations(5):
    print(f"  {obs['ID']}: {obs['POSE']} - {obs['ACTIVITY']}")

print("\nUnacknowledged alerts:")
unack_alerts = client.get_unacknowledged_alerts()
for row in unack_alerts:
    print(f"  {row['ALERT_TYPE']}: {row['QUICK_MESSAGE']} (ID: {row['ID']})")

# Acknowledge the alert we just created (or the first unacknowledged alert)
alert_id_to_ack = created_alert_id or (unack_alerts[0]['ID'] if unack_alerts else None)
if alert_id_to_ack:
    client.update_alert_acknowledged(alert_id_to_ack, "test-user")
    print(f"\nAcknowledged alert {alert_id_to_ack} as test-user")

client.close()
