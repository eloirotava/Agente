import asyncio
import inspect
import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.core import dispatch_hook, processar_orquestracao
from app.db import get_config, init_db
from app.routers import (
    home,
    config,
    hooks,
    knowledge,
)
from app.worker import start_periodic_scheduler


app = FastAPI(title="Agente Rotava - Console Local")
templates = Jinja2Templates(directory="app/templates")


# Permite que o HTML hospedado em outro endereço chame a API.
# Para o primeiro teste, aceita qualquer origem.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Registrando todas as rotas
app.include_router(home.router)
app.include_router(config.router)
app.include_router(hooks.router)
app.include_router(knowledge.router)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def configured_http_router(request: Request, path: str):
    cfg = get_config()
    code = (cfg.get("http_routes_code") or "").strip()
    if not code:
        return HTMLResponse("Rota não configurada. Configure http_routes_code em /config.", status_code=404)

    helpers = {
        "HTMLResponse": HTMLResponse,
        "JSONResponse": JSONResponse,
        "RedirectResponse": RedirectResponse,
        "processar_orquestracao": processar_orquestracao,
        "dispatch_hook": dispatch_hook,
        "templates": templates,
        "json": json,
    }
    scope = {"json": json, **helpers}
    exec(code, scope, scope)
    func = scope.get("rotear") or scope.get("route") or scope.get("executar")
    if not callable(func):
        return HTMLResponse("http_routes_code deve expor rotear(request, path, cfg, helpers).", status_code=500)

    params = inspect.signature(func).parameters
    if len(params) <= 2:
        result = func(request, path)
    elif len(params) == 3:
        result = func(request, path, cfg)
    else:
        result = func(request, path, cfg, helpers)

    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, Response):
        return result
    if isinstance(result, dict):
        return JSONResponse(result)
    return HTMLResponse(str(result or ""))


@app.on_event("startup")
async def startup():
    init_db()

    # Ativa o relógio/worker em background
    asyncio.create_task(start_periodic_scheduler())
