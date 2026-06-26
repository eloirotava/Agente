from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.db import get_all_logs, get_conn # Importei o get_conn para limpar direto

router = APIRouter(prefix="/logs")
templates = Jinja2Templates(directory="app/templates")

@router.get("", response_class=HTMLResponse)
def logs_get(request: Request):
    logs = get_all_logs()
    return templates.TemplateResponse(
        request=request,
        name="logs.html",
        context={"logs": logs, "cleared": request.query_params.get("cleared")}
    )

@router.post("/clear")
def logs_clear():
    # Conecta e apaga todos os registros da tabela de auditoria
    with get_conn() as c:
        c.execute("DELETE FROM interactions_log")
        c.commit()
    return RedirectResponse(url="/logs?cleared=1", status_code=303)
