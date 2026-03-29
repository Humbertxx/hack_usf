from typing import Dict, List

from fastapi import APIRouter, Query

from config import DEFAULT_LIMIT, MAX_LIMIT
from server.snowflake_client import SnowflakeClient

router = APIRouter(prefix="/api/observations", tags=["observations"])


@router.get("")
def list_observations(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> Dict[str, List[dict]]:
    client = SnowflakeClient()
    try:
        observations = client.get_recent_observations(limit=limit)
        return {"observations": observations}
    finally:
        client.close()
