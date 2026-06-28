from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import (
    delete_config_version,
    get_config,
    get_config_versions,
    restore_config_version,
    save_config,
)

router = APIRouter(prefix="/config")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
def config_get(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"cfg": get_config(), "versions": get_config_versions()}
    )

@router.post("", response_class=HTMLResponse)
def config_post(
    request: Request,
    llm_provider_code: str = Form(""),
    scheduler_condition_hard_timeout_seconds: str = Form(""),
    scheduler_maestro_hard_timeout_seconds: str = Form(""),
    scheduler_max_concurrent_jobs: str = Form("1"),
    scheduler_default_hook_slug: str = Form(""),
    change_note: str = Form("")
):
    save_config({
        "llm_provider_code": llm_provider_code,
        "scheduler_condition_hard_timeout_seconds": scheduler_condition_hard_timeout_seconds,
        "scheduler_maestro_hard_timeout_seconds": scheduler_maestro_hard_timeout_seconds,
        "scheduler_max_concurrent_jobs": scheduler_max_concurrent_jobs,
        "scheduler_default_hook_slug": scheduler_default_hook_slug
    }, change_note=change_note)
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={"cfg": get_config(), "versions": get_config_versions(), "saved": True}
    )


@router.post("/versions/restore/{version_id}")
def config_version_restore(version_id: int):
    restored = restore_config_version(version_id)
    suffix = "restored=1" if restored else "restore_missing=1"
    return RedirectResponse(url=f"/config?{suffix}", status_code=303)


@router.post("/versions/delete/{version_id}")
def config_version_delete(version_id: int):
    delete_config_version(version_id)
    return RedirectResponse(url="/config?deleted_version=1", status_code=303)
