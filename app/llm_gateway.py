import asyncio
import inspect
import json
import time
from hashlib import sha256
from typing import Any

CUSTOM_LLM_TEMPLATE = '''# Configure TODO o acesso ao modelo dentro desta def.
# messages pode conter texto, listas multimodais ou qualquer payload que seu backend aceite.
# Retorne sempre texto para o Maestro interpretar.

async def gerar_resposta(messages, cfg):
    return '{"acao":"responder","resposta":"Configure o provider LLM em /config."}'
'''


def config_fingerprint(cfg: dict) -> str:
    safe = {
        key: value
        for key, value in (cfg or {}).items()
        if "key" not in key.lower() and "token" not in key.lower()
    }
    raw = json.dumps(safe, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(raw.encode("utf-8")).hexdigest()[:16]


async def _call_python_provider(cfg: dict, messages: list[dict[str, Any]]) -> str:
    code = (cfg.get("llm_provider_code") or "").strip()
    if not code:
        raise RuntimeError(
            "llm_provider_code está vazio. Configure gerar_resposta(messages, cfg) em /config."
        )

    scope: dict[str, Any] = {}
    exec(code, scope, scope)
    fn = scope.get("gerar_resposta") or scope.get("executar")
    if not callable(fn):
        raise RuntimeError(
            "Provider Python deve expor gerar_resposta(messages, cfg) "
            "ou executar(messages, cfg)."
        )

    started = time.perf_counter()
    if inspect.iscoroutinefunction(fn):
        result = await fn(messages, cfg)
    else:
        result = await asyncio.to_thread(fn, messages, cfg)

    if inspect.isawaitable(result):
        result = await result

    elapsed = time.perf_counter() - started
    print(
        "[LLM] "
        + json.dumps(
            {
                "event": "python_provider_done",
                "elapsed_seconds": round(elapsed, 3),
                "message_count": len(messages),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return str(result)


async def call_llm_messages(cfg: dict, messages: list[dict[str, Any]]) -> str:
    """Chama sempre o provider definido em Python nas configurações."""
    return await _call_python_provider(cfg, messages)
