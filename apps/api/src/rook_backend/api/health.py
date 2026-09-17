"""Process liveness only; no dependency or monitored-service health checks."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


@router.get("/health/live", response_model=LivenessResponse)
def live() -> LivenessResponse:
    """Indicate only that this API process can respond to an HTTP request."""
    return LivenessResponse()
