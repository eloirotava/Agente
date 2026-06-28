import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import (
    home,
    config,
    chat,
    knowledge,
    logs,
    hooks,
)
from app.worker import start_periodic_scheduler


app = FastAPI(title="Agente Rotava - Console Local")


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
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(logs.router)
app.include_router(hooks.router)


@app.on_event("startup")
async def startup():
    init_db()

    # Ativa o relógio/worker em background
    asyncio.create_task(start_periodic_scheduler())
