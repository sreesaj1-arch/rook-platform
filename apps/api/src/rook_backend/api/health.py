"""Independent process liveness and database readiness; no workload health."""

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

router = APIRouter()


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


@router.get("/health/live", response_model=LivenessResponse)
def live() -> LivenessResponse:
    """Indicate only that this API process can respond to an HTTP request."""
    return LivenessResponse()


class ReadinessResponse(BaseModel):
    status: Literal["ready", "unavailable"]


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
async def ready(request: Request, response: Response) -> ReadinessResponse:
    """Check database connectivity without returning connection details."""
    if await request.app.state.database.ready():
        return ReadinessResponse(status="ready")
    response.status_code = 503
    return ReadinessResponse(status="unavailable")
