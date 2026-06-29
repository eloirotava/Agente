from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import (
    delete_config_version,
    delete_endpoint_version,
    delete_task,
    get_config,
    get_config_versions,
    get_all_tasks,
    get_endpoint_version,
    get_endpoint_versions,
    get_task,
    restore_config_version,
    restore_endpoint_version,
    save_config,
    save_task,
    update_task,
)

router = APIRouter(prefix="/config")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
def config_get(request: Request):
    edit_id = request.query_params.get("edit_task")
    edit_task = get_task(int(edit_id)) if edit_id and edit_id.isdigit() else None
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={
            "cfg": get_config(),
            "versions": get_config_versions(),
            "tasks": get_all_tasks(),
            "edit_task": edit_task,
            "task_versions": get_endpoint_versions("task", str(edit_task["id"])) if edit_task else [],
        }
    )

@router.post("", response_class=HTMLResponse)
def config_post(
    request: Request,
    llm_provider_code: str = Form(""),
    assistant_html_code: str = Form(""),
    assistant_handler_code: str = Form(""),
    scheduler_condition_hard_timeout_seconds: str = Form(""),
    scheduler_maestro_hard_timeout_seconds: str = Form(""),
    scheduler_max_concurrent_jobs: str = Form("1"),
    scheduler_default_hook_slug: str = Form(""),
    scheduler_dispatch_code: str = Form(""),
    maestro_core_code: str = Form(""),
    log_persist_code: str = Form(""),
    change_note: str = Form("")
):
    save_config({
        "llm_provider_code": llm_provider_code,
        "assistant_html_code": assistant_html_code,
        "assistant_handler_code": assistant_handler_code,
        "scheduler_condition_hard_timeout_seconds": scheduler_condition_hard_timeout_seconds,
        "scheduler_maestro_hard_timeout_seconds": scheduler_maestro_hard_timeout_seconds,
        "scheduler_max_concurrent_jobs": scheduler_max_concurrent_jobs,
        "scheduler_default_hook_slug": scheduler_default_hook_slug,
        "scheduler_dispatch_code": scheduler_dispatch_code,
        "maestro_core_code": maestro_core_code,
        "log_persist_code": log_persist_code
    }, change_note=change_note)
    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={
            "cfg": get_config(),
            "versions": get_config_versions(),
            "tasks": get_all_tasks(),
            "edit_task": None,
            "task_versions": [],
            "saved": True,
        }
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


@router.post("/tasks")
def config_task_save(
    task_id: str = Form(""),
    title: str = Form(...),
    schedule_hours: str = Form(...),
    condition_script: str = Form(""),
    prompt: str = Form(...),
    change_note: str = Form(""),
):
    if task_id and task_id.isdigit():
        update_task(int(task_id), title, prompt, schedule_hours, condition_script, change_note=change_note)
        return RedirectResponse(url=f"/config?edit_task={task_id}&task_saved=1", status_code=303)

    save_task(title, prompt, schedule_hours, condition_script, change_note=change_note)
    return RedirectResponse(url="/config?task_saved=1", status_code=303)


@router.post("/tasks/delete/{task_id}")
def config_task_delete(task_id: int):
    delete_task(task_id)
    return RedirectResponse(url="/config?task_deleted=1", status_code=303)


@router.post("/tasks/versions/restore/{version_id}")
def config_task_version_restore(version_id: int):
    version = restore_endpoint_version(version_id)
    if not version:
        return RedirectResponse(url="/config?task_restore_missing=1", status_code=303)
    return RedirectResponse(url=f"/config?edit_task={version['slug']}&task_restored=1", status_code=303)


@router.post("/tasks/versions/delete/{version_id}")
def config_task_version_delete(version_id: int):
    version = get_endpoint_version(version_id)
    delete_endpoint_version(version_id)
    if version:
        return RedirectResponse(url=f"/config?edit_task={version['slug']}&task_version_deleted=1", status_code=303)
    return RedirectResponse(url="/config?task_version_deleted=1", status_code=303)
