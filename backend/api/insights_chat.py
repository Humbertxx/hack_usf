"""
POST /api/insights-chat — Cortex-backed chat using seven-day insights context.
"""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from backend.server.demo_snowflake_guard import (
        demo_snowflake_guard_detail,
        snowflake_database_allows_demo_reads,
    )
    from backend.server.snowflake_client import SnowflakeClient
except ImportError:
    from server.demo_snowflake_guard import (
        demo_snowflake_guard_detail,
        snowflake_database_allows_demo_reads,
    )
    from server.snowflake_client import SnowflakeClient

router = APIRouter(prefix="/api/insights-chat", tags=["insights-chat"])


class InsightsChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=3000)
    person_id: str = Field(default="grandma")


def _normalize_person_id(raw: str) -> str:
    person_id = (raw or "").strip().lower()
    if person_id not in ("grandma", "grandpa"):
        raise HTTPException(status_code=400, detail="person_id must be 'grandma' or 'grandpa'")
    return person_id


@router.post("")
def insights_chat(payload: InsightsChatRequest) -> Dict[str, Any]:
    if not snowflake_database_allows_demo_reads():
        raise HTTPException(status_code=403, detail=demo_snowflake_guard_detail())

    person_id = _normalize_person_id(payload.person_id)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    model = (os.getenv("SNOWFLAKE_CORTEX_MODEL") or "mistral-large").strip() or "mistral-large"

    client = SnowflakeClient()
    try:
        result = client.complete_insights_chat(
            person_id=person_id,
            user_message=message,
            model=model,
        )
        return {
            "person_id": person_id,
            "model": result.get("model", model),
            "reply": result.get("reply", ""),
            "context": result.get("context", {}),
        }
    finally:
        client.close()
