from __future__ import annotations

import asyncio
import inspect
import json
import traceback
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import delete_hook, get_all_hooks, get_hook, save_hook
from app.core import processar_orquestracao

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _safe_slug(slug: str) -> str:
    return slug.strip().lower().replace(" ", "_")


def _headers_dict(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.headers.items()}


async def _call_receber(func: Any, payload: dict[str, Any], headers: dict[str, str]) -> Any:
    try:
        result = func(payload, headers)
    except TypeError:
        result = func(payload)

    if inspect.isawaitable(result):
        return await result
    return result


def _with_hook_context(hook: dict[str, Any], mensagem: str, contexto: Any = None) -> str:
    partes = [mensagem]

    descricao = (hook.get("description") or "").strip()
    if descricao:
        partes.append(f"DESCRIÇÃO DO HOOK:\n{descricao}")

    if contexto:
        partes.append(f"CONTEXTO DO HOOK:\n{contexto}")

    return "\n\n".join(partes)


def _build_maestro_input(slug: str, hook: dict[str, Any], payload: dict[str, Any], result: Any) -> tuple[str, str]:
    origem = f"HOOK: {hook.get('title') or slug}"

    if isinstance(result, dict):
        origem = str(result.get("origem") or origem)
        mensagem = result.get("mensagem") or result.get("message") or result.get("texto")
        contexto = result.get("contexto") or result.get("context")

        if mensagem is None:
            mensagem = json.dumps(result, ensure_ascii=False, indent=2)

        return _with_hook_context(hook, str(mensagem), contexto), origem

    if isinstance(result, str):
        return _with_hook_context(hook, result), origem

    if result is None:
        return (
            _with_hook_context(
                hook,
                "Evento recebido via hook. JSON bruto:\n"
                + json.dumps(payload, ensure_ascii=False, indent=2),
            ),
            origem,
        )

    return _with_hook_context(hook, str(result)), origem


async def _run_maestro_from_hook(mensagem: str, origem: str) -> None:
    try:
        await processar_orquestracao(mensagem=mensagem, origem=origem)
    except Exception as exc:
        print(f"Erro ao processar hook no Maestro: {exc}")


async def dispatch_hook(slug: str, payload: dict[str, Any], headers: dict[str, str] | None = None):
    hook = get_hook(slug)
    if not hook or int(hook.get("active") or 0) != 1:
        raise HTTPException(status_code=404, detail="Hook não encontrado ou inativo.")

    code = (hook.get("content") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Hook sem código Python receber().")

    local_scope: dict[str, Any] = {}
    try:
        exec(code, {}, local_scope)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao carregar script do hook: {exc}") from exc

    receber = local_scope.get("receber")
    if not receber:
        raise HTTPException(status_code=400, detail="Script do hook não expõe a função receber(payload, headers).")

    try:
        result = await asyncio.to_thread(lambda: receber(payload, headers or {}))
        if inspect.isawaitable(result):
            result = await result
    except TypeError:
        try:
            result = await asyncio.to_thread(lambda: receber(payload))
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            trace = traceback.format_exc()
            raise HTTPException(status_code=500, detail=f"Erro ao executar receber(): {exc}\n{trace}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        trace = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Erro ao executar receber(): {exc}\n{trace}") from exc

    mensagem, origem = _build_maestro_input(slug, hook, payload, result)
    asyncio.create_task(_run_maestro_from_hook(mensagem, origem))

    return {
        "ok": True,
        "hook": slug,
        "origem": origem,
        "status": "recebido",
        "mensagem": "Recebido com sucesso.",
    }


@router.post("/hook/{slug}")
async def hook_post(slug: str, request: Request):
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Envie um corpo JSON válido.") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="O corpo do hook deve ser um objeto JSON.")

    return JSONResponse(await dispatch_hook(slug, payload, _headers_dict(request)))


@router.get("/hooks", response_class=HTMLResponse)
def hooks_get(request: Request, hook: str = "", novo: int = 0):
    hooks = get_all_hooks()
    selected_slug = "" if novo else (hook or (hooks[0]["slug"] if hooks else ""))
    selected_hook = get_hook(selected_slug) if selected_slug else None

    return templates.TemplateResponse(
        request=request,
        name="hooks.html",
        context={
            "hooks": hooks,
            "hook_atual": selected_hook,
            "hook_selecionado": selected_slug if selected_hook else "",
            "saved": request.query_params.get("saved"),
            "deleted": request.query_params.get("deleted"),
        },
    )


@router.post("/hooks", response_class=HTMLResponse)
def hooks_post(
    slug: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    content: str = Form(...),
    active: str = Form("0"),
):
    safe_slug = _safe_slug(slug)
    save_hook(safe_slug, title, description, content, 1 if active == "1" else 0)
    return RedirectResponse(url=f"/hooks?hook={safe_slug}&saved=1", status_code=303)


@router.post("/hooks/delete/{slug}")
def hooks_delete(slug: str):
    delete_hook(slug)
    return RedirectResponse(url="/hooks?deleted=1", status_code=303)
