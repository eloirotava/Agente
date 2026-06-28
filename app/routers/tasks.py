from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import (
    delete_endpoint_version,
    delete_task,
    get_all_tasks,
    get_endpoint_version,
    get_endpoint_versions,
    get_task,
    restore_endpoint_version,
    save_task,
    update_task,
)

router = APIRouter(prefix="/tasks")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
def tasks_get(request: Request, edit_id: int = None):
    # Se houver um edit_id no URL, puxa a tarefa para preencher o formulário
    edit_task = get_task(edit_id) if edit_id else None

    return templates.TemplateResponse(
        request=request,
        name="tasks.html",
        context={
            "tasks": get_all_tasks(),
            "edit_task": edit_task,
            "versions": get_endpoint_versions("task", str(edit_id)) if edit_task else [],
            "restored": request.query_params.get("restored"),
            "version_deleted": request.query_params.get("version_deleted"),
        }
    )

@router.post("", response_class=HTMLResponse)
def tasks_post(
    task_id: int = Form(None),
    title: str = Form(...),
    prompt: str = Form(...),
    schedule_hours: str = Form(...),
    condition_script: str = Form(""),
    change_note: str = Form("")
):
    if task_id:
        # Se veio um ID oculto, é uma edição
        update_task(task_id, title, prompt, schedule_hours, condition_script, change_note=change_note)
    else:
        # Se não veio ID, é uma criação nova
        save_task(title, prompt, schedule_hours, condition_script, change_note=change_note)

    return RedirectResponse(url="/tasks", status_code=303)

@router.post("/delete/{task_id}")
def tasks_delete(task_id: int):
    delete_task(task_id)
    return RedirectResponse(url="/tasks", status_code=303)


@router.post("/versions/restore/{version_id}")
def tasks_version_restore(version_id: int):
    version = restore_endpoint_version(version_id)
    if not version:
        return RedirectResponse(url="/tasks", status_code=303)
    return RedirectResponse(url=f"/tasks?edit_id={version['slug']}&restored=1", status_code=303)


@router.post("/versions/delete/{version_id}")
def tasks_version_delete(version_id: int):
    version = get_endpoint_version(version_id)
    delete_endpoint_version(version_id)
    if version:
        return RedirectResponse(url=f"/tasks?edit_id={version['slug']}&version_deleted=1", status_code=303)
    return RedirectResponse(url="/tasks?version_deleted=1", status_code=303)
