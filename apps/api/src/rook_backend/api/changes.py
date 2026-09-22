"""Explicit local recording of observed changes; no deployment execution."""

import time
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from rook_backend.changes import ChangeConflict, ChangeEvent, ChangeStore
from rook_backend.incident_store import PostgresIncidentStore
from rook_backend.telemetry import SERVICE, Unavailable

router = APIRouter()


def change_store(request: Request) -> ChangeStore:
    return ChangeStore(PostgresIncidentStore(request.app.state.database))


@router.post('/changes', response_model=ChangeEvent, status_code=201)
async def record_change(request: Request, event: ChangeEvent) -> ChangeEvent | JSONResponse:
    if event.environment != request.app.state.settings.change_environment:
        return JSONResponse(status_code=422, content={'status': 'environment_mismatch'})
    if event.service_namespace != request.app.state.settings.prometheus_namespace:
        return JSONResponse(status_code=422, content={'status': 'namespace_mismatch'})
    try:
        return await change_store(request).record(event)
    except ChangeConflict:
        return JSONResponse(status_code=409, content={'status': 'event_id_conflict'})
    except Unavailable:
        return JSONResponse(status_code=503, content={'status': 'unavailable'})


@router.get('/services/{service_name}/changes', response_model=list[ChangeEvent])
async def recent_changes(request: Request, service_name: Annotated[str, Path(pattern=f'^{SERVICE}$')],
                         lookback_seconds: int = Query(3600, ge=1, le=86400),
                         limit: int = Query(100, ge=1, le=100)) -> list[ChangeEvent] | JSONResponse:
    settings = request.app.state.settings
    now = time.time()
    try:
        return await change_store(request).recent(service_name, settings.prometheus_namespace,
            settings.change_environment, now - lookback_seconds, now, limit)
    except Unavailable:
        return JSONResponse(status_code=503, content={'status': 'unavailable'})
