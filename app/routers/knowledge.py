from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import (
    get_context, get_general_contexts, save_context, delete_context,
    get_tool, get_all_tools, save_tool, delete_tool
)

router = APIRouter(prefix="/knowledge")
templates = Jinja2Templates(directory="app/templates")


def _safe_slug(slug: str) -> str:
    return slug.strip().lower().replace(" ", "_")


def _system_context() -> dict:
    system_ctx = get_context("system_prompt") or {
        "slug": "system_prompt",
        "title": "Diretriz Operacional Base",
        "description_for_ai": "",
        "content": "",
        "bootstrap_json": "",
    }
    system_ctx = dict(system_ctx)
    system_ctx["title"] = "Diretriz Operacional Base"
    system_ctx["kind"] = "context"
    system_ctx["kind_label"] = "Contexto inicial"
    system_ctx["select_value"] = "context:system_prompt"
    return system_ctx


def _endpoint_options() -> list[dict]:
    endpoints = [_system_context()]

    for ctx in get_general_contexts():
        item = dict(ctx)
        item["kind"] = "context"
        item["kind_label"] = "Manual"
        item["select_value"] = f"context:{item['slug']}"
        endpoints.append(item)

    for tool in get_all_tools():
        item = dict(tool)
        item["kind"] = "tool"
        item["kind_label"] = "Python"
        item["select_value"] = f"tool:{item['slug']}"
        endpoints.append(item)

    return endpoints


def _selected_endpoint(selected: str) -> tuple[str, str, dict | None]:
    if not selected:
        return "", "", None

    kind, _, slug = selected.partition(":")
    if not slug:
        slug = kind
        kind = "tool" if get_tool(slug) else "context"

    if kind == "context":
        endpoint = get_context(slug)
        if endpoint and slug == "system_prompt":
            endpoint = _system_context()
        elif endpoint:
            endpoint = dict(endpoint)
            endpoint["kind"] = "context"
            endpoint["kind_label"] = "Manual"
        return kind, slug, endpoint

    endpoint = get_tool(slug)
    if endpoint:
        endpoint = dict(endpoint)
        endpoint["kind"] = "tool"
        endpoint["kind_label"] = "Python"
    return "tool", slug, endpoint


@router.get("/system")
def system_get():
    return RedirectResponse(url="/knowledge/tools?endpoint=context:system_prompt", status_code=303)


@router.post("/system", response_class=HTMLResponse)
def system_post(
    request: Request,
    content: str = Form(...),
    bootstrap_json: str = Form("")
):
    save_context(
        "system_prompt",
        "Diretriz Operacional Base",
        "",
        content,
        bootstrap_json=bootstrap_json
    )
    return RedirectResponse(url="/knowledge/tools?endpoint=context:system_prompt&saved=1", status_code=303)


@router.get("/tools", response_class=HTMLResponse)
def tools_get(request: Request, endpoint: str = "", slug: str = "", novo: int = 0):
    selected = "" if novo else (endpoint or (f"tool:{slug}" if slug else "context:system_prompt"))
    kind, selected_slug, endpoint_atual = _selected_endpoint(selected)
    if endpoint_atual and endpoint_atual.get("slug") == "system_prompt":
        kind = "context"
        selected = "context:system_prompt"

    return templates.TemplateResponse(
        request=request,
        name="knowledge_tools.html",
        context={
            "endpoints": _endpoint_options(),
            "endpoint_atual": endpoint_atual,
            "endpoint_kind": kind,
            "endpoint_selecionado": selected if endpoint_atual else "",
            "slug_selecionado": selected_slug if endpoint_atual else "",
            "saved": request.query_params.get("saved"),
            "deleted": request.query_params.get("deleted"),
            "protected": request.query_params.get("protected"),
        }
    )


@router.post("/tools", response_class=HTMLResponse)
def tools_post(
    request: Request,
    slug: str = Form(...),
    title: str = Form(...),
    description_for_ai: str = Form(""),
    tool_context: str = Form(""),
    content: str = Form(""),
    bootstrap_json: str = Form("")
):
    safe_slug = _safe_slug(slug)
    code = content.strip()

    if safe_slug == "system_prompt":
        save_context(
            "system_prompt",
            "Diretriz Operacional Base",
            "",
            tool_context,
            bootstrap_json=bootstrap_json,
        )
        return RedirectResponse(url="/knowledge/tools?endpoint=context:system_prompt&saved=1", status_code=303)

    if code:
        save_tool(safe_slug, title, description_for_ai, tool_context, content)
        delete_context(safe_slug)
        return RedirectResponse(url=f"/knowledge/tools?endpoint=tool:{safe_slug}&saved=1", status_code=303)

    save_context(safe_slug, title, description_for_ai, tool_context, bootstrap_json="")
    delete_tool(safe_slug)
    return RedirectResponse(url=f"/knowledge/tools?endpoint=context:{safe_slug}&saved=1", status_code=303)


@router.post("/tools/delete/{kind}/{slug}")
def tools_delete(kind: str, slug: str):
    if slug == "system_prompt":
        return RedirectResponse(url="/knowledge/tools?endpoint=context:system_prompt&protected=1", status_code=303)

    if kind == "context":
        delete_context(slug)
    elif kind == "tool":
        delete_tool(slug)
    else:
        delete_context(slug)
        delete_tool(slug)

    return RedirectResponse(url="/knowledge/tools?deleted=1", status_code=303)


@router.post("/tools/delete/{slug}")
def tools_delete_legacy(slug: str):
    if slug == "system_prompt":
        return RedirectResponse(url="/knowledge/tools?endpoint=context:system_prompt&protected=1", status_code=303)
    delete_tool(slug)
    delete_context(slug)
    return RedirectResponse(url="/knowledge/tools?deleted=1", status_code=303)


@router.get("/general", response_class=HTMLResponse)
def general_get(slug: str = "", novo: int = 0):
    if novo:
        return RedirectResponse(url="/knowledge/tools?novo=1", status_code=303)
    endpoint = f"context:{slug or 'system_prompt'}"
    return RedirectResponse(url=f"/knowledge/tools?endpoint={endpoint}", status_code=303)


@router.post("/general", response_class=HTMLResponse)
def general_post(
    request: Request,
    slug: str = Form(...),
    title: str = Form(...),
    description_for_ai: str = Form(""),
    content: str = Form(...),
    bootstrap_json: str = Form("")
):
    safe_slug = _safe_slug(slug)
    if safe_slug == "system_prompt":
        save_context(
            "system_prompt",
            "Diretriz Operacional Base",
            "",
            content,
            bootstrap_json=bootstrap_json,
        )
    else:
        save_context(safe_slug, title, description_for_ai, content, bootstrap_json="")
    return RedirectResponse(url=f"/knowledge/tools?endpoint=context:{safe_slug}&saved=1", status_code=303)


@router.post("/general/delete/{slug}")
def general_delete(slug: str):
    if slug == "system_prompt":
        return RedirectResponse(url="/knowledge/tools?endpoint=context:system_prompt&protected=1", status_code=303)
    delete_context(slug)
    return RedirectResponse(url="/knowledge/tools?deleted=1", status_code=303)
