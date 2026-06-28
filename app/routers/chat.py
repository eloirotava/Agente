import inspect
import json

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from app.core import processar_orquestracao
from app.db import get_config

router = APIRouter(prefix="/chat")
templates = Jinja2Templates(directory="app/templates")


def _render_assistant_html(html: str, **values) -> str:
    rendered = html or ""
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", str(value))
        rendered = rendered.replace("{{" + key + "}}", str(value))
    return rendered


def _default_context(message: str = "", answer: str = "", logs: list | None = None) -> dict:
    return {"message": message, "answer": answer, "logs": logs or []}


async def _run_assistant_handler(request: Request, cfg: dict) -> Response:
    code = (cfg.get("assistant_handler_code") or "").strip()
    html = cfg.get("assistant_html_code") or ""
    helpers = {
        "processar_orquestracao": processar_orquestracao,
        "render_html": lambda **values: HTMLResponse(_render_assistant_html(html, **values)),
        "json": json,
    }
    scope = {"json": json, **helpers}
    exec(code, scope, scope)
    func = scope.get("atender") or scope.get("executar") or scope.get("handle")
    if not callable(func):
        raise RuntimeError("Def do assistente deve expor atender(request, cfg, helpers) ou executar(...).")

    params = inspect.signature(func).parameters
    if len(params) <= 1:
        result = func(request)
    elif len(params) == 2:
        result = func(request, cfg)
    else:
        result = func(request, cfg, helpers)

    if inspect.isawaitable(result):
        result = await result

    if isinstance(result, Response):
        return result
    if isinstance(result, dict):
        if "html" in result:
            return HTMLResponse(str(result["html"]))
        return HTMLResponse(_render_assistant_html(html, **result))
    return HTMLResponse(str(result or ""))


@router.get("", response_class=HTMLResponse)
def chat_get(request: Request):
    cfg = get_config()
    html = (cfg.get("assistant_html_code") or "").strip()
    if html:
        return HTMLResponse(
            _render_assistant_html(
                html,
                answer="",
                error="",
                logs_json="[]",
                assistant_payload_json="{}",
            )
        )
    return templates.TemplateResponse(request=request, name="chat.html", context={})

@router.post("", response_class=HTMLResponse)
async def chat_post(request: Request, message: str = Form("")):
    cfg = get_config()
    if (cfg.get("assistant_handler_code") or "").strip():
        try:
            return await _run_assistant_handler(request, cfg)
        except Exception as exc:
            html = (cfg.get("assistant_html_code") or "").strip()
            if html:
                return HTMLResponse(
                    _render_assistant_html(
                        html,
                        answer="",
                        error=str(exc),
                        logs_json="[]",
                        assistant_payload_json="{}",
                    ),
                    status_code=500,
                )
            return HTMLResponse(f"Erro no assistente configurado: {exc}", status_code=500)

    # A MÁGICA: O Chat não tem mais cérebro. Ele consome o serviço do Maestro!
    resultado = await processar_orquestracao(mensagem=message, origem="Chat")

    return templates.TemplateResponse(
        request=request,
        name="chat.html",
        context={
            "message": message,
            "answer": resultado["resposta_final"],
            "logs": resultado["logs"]
        }
    )
