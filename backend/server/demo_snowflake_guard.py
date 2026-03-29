"""
Dev-database guard for demo-only Snowflake readers (insights, primary-state, etc.).

Refuses production and unknown databases unless ALLOW_NON_DEV_SNOWFLAKE_FOR_INSIGHTS
is set (emergency override; off by default).
"""

from __future__ import annotations

import os


def snowflake_database_allows_demo_reads() -> bool:
    raw = (os.getenv("ALLOW_NON_DEV_SNOWFLAKE_FOR_INSIGHTS") or "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    db = (os.getenv("SNOWFLAKE_DATABASE") or "").strip()
    if not db:
        return False
    u = db.upper()
    if u == "GRANDMA_MONITOR":
        return False
    if u == "GRANDMA_MONITOR_DEV" or u.endswith("_DEV"):
        return True
    return False


def demo_snowflake_guard_detail() -> str:
    db = (os.getenv("SNOWFLAKE_DATABASE") or "").strip()
    if (os.getenv("ALLOW_NON_DEV_SNOWFLAKE_FOR_INSIGHTS") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return "Demo Snowflake guard bypassed via ALLOW_NON_DEV_SNOWFLAKE_FOR_INSIGHTS."
    if not db:
        return "SNOWFLAKE_DATABASE is not set; this route is limited to configured dev databases."
    return (
        f"Database {db!r} is not allowed for demo reads. "
        "Use GRANDMA_MONITOR_DEV or a name ending in _DEV, or set "
        "ALLOW_NON_DEV_SNOWFLAKE_FOR_INSIGHTS for emergency override."
    )
