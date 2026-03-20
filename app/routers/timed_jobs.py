"""Timed job routes: CRUD, trigger, and auth-alert status."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import TimedJob, delete_timed_job, list_timed_jobs, load_settings, upsert_timed_job
from ..timed_jobs import (
    get_timed_job_auth_alert_provider_ids_for_status,
    get_timed_job_channel_options,
    trigger_timed_job_now,
)

router = APIRouter()


class TimedJobWriteRequest(BaseModel):
    title: str = Field(default="", max_length=120)
    prompt: str = Field(default="", max_length=5000)
    interval: Literal[
        "daily",
        "weekly",
        "monthly",
        "once",
        "hourly",
        "every_2_hours",
        "every_30_min",
        "every_15_min",
        "every_10_min",
        "every_5_min",
    ] = "daily"
    start_date: str = ""
    time_of_day: str = "00:00"
    enabled: bool = False
    output_decision_enabled: bool = False
    channels: list[str] = Field(default_factory=lambda: ["gateway"])
    provider_id: str = ""
    model: str = ""


class TimedJobsResponse(BaseModel):
    jobs: list[TimedJob]
    channels: list[dict[str, object]]


class TimedJobAuthAlertStatusResponse(BaseModel):
    active: bool
    provider_ids: list[str] = Field(default_factory=list)
    detail: str = ""


async def _validate_timed_job_provider_model_payload(payload: TimedJobWriteRequest) -> None:
    provider_id = payload.provider_id.strip().lower()
    model = payload.model.strip()
    if model and not provider_id:
        raise HTTPException(status_code=422, detail="Timed job model requires a provider selection.")
    if not provider_id:
        return

    settings = await load_settings()
    provider_config = settings.provider_configs.get(provider_id)
    if provider_config is None:
        raise HTTPException(status_code=422, detail="Timed job provider is not configured.")


@router.get("/api/timed-jobs", response_model=TimedJobsResponse)
async def get_timed_jobs() -> TimedJobsResponse:
    settings = await load_settings()
    jobs = await list_timed_jobs()
    channels = get_timed_job_channel_options(settings)
    return TimedJobsResponse(jobs=jobs, channels=channels)


@router.get("/api/timed-jobs/auth-alert-status", response_model=TimedJobAuthAlertStatusResponse)
async def get_timed_job_auth_alert_status() -> TimedJobAuthAlertStatusResponse:
    provider_ids = await get_timed_job_auth_alert_provider_ids_for_status()
    detail = ""
    if provider_ids:
        joined = ", ".join(provider_ids)
        detail = (
            "Timed jobs detected expired provider authentication and suppressed repeated alerts "
            f"for: {joined}. Reconnect the provider in Setup."
        )
    return TimedJobAuthAlertStatusResponse(
        active=bool(provider_ids),
        provider_ids=provider_ids,
        detail=detail,
    )


@router.post("/api/timed-jobs", response_model=TimedJob)
async def create_timed_job(payload: TimedJobWriteRequest) -> TimedJob:
    if not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="Timed job prompt is required.")
    if not payload.channels:
        raise HTTPException(status_code=422, detail="At least one output channel is required.")
    await _validate_timed_job_provider_model_payload(payload)
    return await upsert_timed_job(payload.model_dump())


@router.put("/api/timed-jobs/{timed_job_id}", response_model=TimedJob)
async def update_timed_job(timed_job_id: str, payload: TimedJobWriteRequest) -> TimedJob:
    if not timed_job_id.strip():
        raise HTTPException(status_code=422, detail="Timed job id is required.")
    if not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="Timed job prompt is required.")
    if not payload.channels:
        raise HTTPException(status_code=422, detail="At least one output channel is required.")
    await _validate_timed_job_provider_model_payload(payload)
    return await upsert_timed_job(payload.model_dump(), timed_job_id=timed_job_id)


@router.delete("/api/timed-jobs/{timed_job_id}")
async def remove_timed_job(timed_job_id: str) -> dict[str, object]:
    deleted = await delete_timed_job(timed_job_id)
    return {"ok": True, "deleted": deleted}


@router.post("/api/timed-jobs/{timed_job_id}/trigger")
async def trigger_timed_job(timed_job_id: str) -> dict[str, object]:
    if not timed_job_id.strip():
        raise HTTPException(status_code=422, detail="Timed job id is required.")
    found = await trigger_timed_job_now(timed_job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Timed job not found.")
    return {"ok": True}
