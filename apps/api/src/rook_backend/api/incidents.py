"""Incident retrieval and explicit actions; HTTP never schedules evaluation."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from rook_backend.incident_store import PostgresIncidentStore
from rook_backend.incidents import Incident, IncidentState, InvalidTransition
from rook_backend.telemetry import Unavailable

router = APIRouter()


def incident_store(request: Request) -> PostgresIncidentStore:
    return PostgresIncidentStore(request.app.state.database)


@router.get("/incidents", response_model=list[Incident])
async def list_incidents(request: Request, limit: int = Query(100, ge=1, le=100),
                         offset: int = Query(0, ge=0, le=100000)) -> list[Incident] | JSONResponse:
    try:
        return await incident_store(request).list(limit, offset)
    except Unavailable:
        return JSONResponse(status_code=503, content={"status": "unavailable"})


@router.get("/incidents/{incident_id}", response_model=Incident)
async def get_incident(request: Request, incident_id: UUID) -> Incident | JSONResponse:
    try:
        incident = await incident_store(request).get(incident_id)
    except Unavailable:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    if incident is None:
        return JSONResponse(status_code=404, content={"status": "not_found"})
    return incident


async def transition(request: Request, incident_id: UUID, target: IncidentState) -> Incident | JSONResponse:
    try:
        incident = await incident_store(request).transition(incident_id, target)
    except InvalidTransition:
        return JSONResponse(status_code=409, content={"status": "invalid_transition"})
    except Unavailable:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    if incident is None:
        return JSONResponse(status_code=404, content={"status": "not_found"})
    return incident


@router.post("/incidents/{incident_id}/acknowledge", response_model=Incident)
async def acknowledge_incident(request: Request, incident_id: UUID) -> Incident | JSONResponse:
    return await transition(request, incident_id, "acknowledged")


@router.post("/incidents/{incident_id}/resolve", response_model=Incident)
async def resolve_incident(request: Request, incident_id: UUID) -> Incident | JSONResponse:
    return await transition(request, incident_id, "resolved")
