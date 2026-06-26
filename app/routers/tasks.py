from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import get_all_tasks, get_task, save_task, update_task, delete_task

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
            "edit_task": edit_task
        }
    )

@router.post("", response_class=HTMLResponse)
def tasks_post(
    task_id: int = Form(None),
    title: str = Form(...),
    prompt: str = Form(...),
    schedule_hours: str = Form(...),
    condition_script: str = Form("") # Novo campo opcional
):
    if task_id:
        # Se veio um ID oculto, é uma edição
        update_task(task_id, title, prompt, schedule_hours, condition_script)
    else:
        # Se não veio ID, é uma criação nova
        save_task(title, prompt, schedule_hours, condition_script)

    return RedirectResponse(url="/tasks", status_code=303)

@router.post("/delete/{task_id}")
def tasks_delete(task_id: int):
    delete_task(task_id)
    return RedirectResponse(url="/tasks", status_code=303)
