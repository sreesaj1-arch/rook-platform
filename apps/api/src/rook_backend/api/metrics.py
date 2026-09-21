"""Read-only service metrics endpoint."""

from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from rook_backend.telemetry import SERVICE, ServiceMetrics, Unavailable

router = APIRouter()


@router.get("/services/{service_name}/metrics", response_model=ServiceMetrics)
async def service_metrics(request: Request, service_name: Annotated[str, Path(pattern=f"^{SERVICE}$")]) -> ServiceMetrics | JSONResponse:
    try:
        return await request.app.state.prometheus.metrics(service_name)
    except Unavailable:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
