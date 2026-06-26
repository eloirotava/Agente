import asyncio
import inspect
import json
import time
from hashlib import sha256
from typing import Any

CUSTOM_LLM_TEMPLATE = '''# Defina uma função async ou sync chamada gerar_resposta(messages, cfg).
# messages pode conter texto, listas multimodais ou qualquer payload que seu backend aceite.
# Retorne sempre texto final para o Maestro interpretar.

async def gerar_resposta(messages, cfg):
    return '{"acao":"responder","resposta":"Provider Python configurado."}'
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
        raise RuntimeError("llm_provider_code está vazio.")

    scope: dict[str, Any] = {}
    exec(code, {}, scope)
    fn = scope.get("gerar_resposta") or scope.get("executar")
    if not callable(fn):
        raise RuntimeError(
            "Provider Python deve expor gerar_resposta(messages, cfg) "
            "ou executar(messages, cfg)."
        )

    started = time.perf_counter()
    result = fn(messages, cfg)
    if inspect.isawaitable(result):
        result = await result
    else:
        result = await asyncio.to_thread(lambda: result)

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
    """Ponto único de chamada LLM do core do Maestro."""
    mode = str(cfg.get("llm_provider_mode") or "builtin").strip().lower()
    if mode in {"", "builtin", "apim", "openai_compatible"}:
        from app.apim_client import call_chat_messages

        return await call_chat_messages(cfg, messages)
    if mode in {"python", "custom_python", "def"}:
        return await _call_python_provider(cfg, messages)
    raise RuntimeError(
        f"llm_provider_mode desconhecido: {mode}. Use builtin ou python."
    )
