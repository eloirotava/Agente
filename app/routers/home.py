from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import DB_PATH, get_config, get_conn
from app.settings import API_KEY

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _scalar(conn, sql: str, params: tuple = ()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def get_health_snapshot():
    cfg = get_config()
    db_size_mb = round(DB_PATH.stat().st_size / (1024 * 1024), 2) if DB_PATH.exists() else 0

    with get_conn() as conn:
        total_docs = _scalar(conn, "SELECT COUNT(*) FROM bot_contexts WHERE slug != 'system_prompt'") or 0
        announced_docs = _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM bot_contexts
            WHERE slug != 'system_prompt'
              AND TRIM(COALESCE(description_for_ai, '')) != ''
            """,
        ) or 0
        total_tools = _scalar(conn, "SELECT COUNT(*) FROM bot_tools") or 0
        announced_tools = _scalar(
            conn,
            "SELECT COUNT(*) FROM bot_tools WHERE TRIM(COALESCE(description_for_ai, '')) != ''",
        ) or 0
        total_tasks = _scalar(conn, "SELECT COUNT(*) FROM bot_tasks") or 0
        active_tasks = _scalar(conn, "SELECT COUNT(*) FROM bot_tasks WHERE active = 1") or 0
        total_hooks = _scalar(conn, "SELECT COUNT(*) FROM bot_hooks") or 0
        active_hooks = _scalar(conn, "SELECT COUNT(*) FROM bot_hooks WHERE active = 1") or 0
        total_logs = _scalar(conn, "SELECT COUNT(*) FROM interactions_log") or 0
        last_log_at = _scalar(conn, "SELECT MAX(timestamp) FROM interactions_log") or "Sem interações"
        watchdog = _scalar(conn, "SELECT v FROM config_kv WHERE k = ?", ("ultimo_scan_watchdog",)) or "Aguardando primeiro ciclo do agendador"

    return {
        "api_key_set": bool(API_KEY),
        "provider": cfg.get("api_provider", "azure"),
        "deployment_id": cfg.get("deployment_id", ""),
        "db_path": str(DB_PATH),
        "db_size_mb": db_size_mb,
        "total_docs": total_docs,
        "announced_docs": announced_docs,
        "total_tools": total_tools,
        "announced_tools": announced_tools,
        "total_tasks": total_tasks,
        "active_tasks": active_tasks,
        "total_hooks": total_hooks,
        "active_hooks": active_hooks,
        "total_logs": total_logs,
        "last_log_at": last_log_at,
        "watchdog": watchdog,
    }


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"health": get_health_snapshot()},
    )
