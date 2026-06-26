import asyncio
import json
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.settings import API_KEY


OPENAI_COMPATIBLE_PROVIDERS = {"openai", "gemini", "google"}

# Evita que chat, agenda, Telegram e Discord façam chamadas simultâneas
# ao mesmo deployment dentro deste processo.
MODEL_SEMAPHORE = asyncio.Semaphore(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEBUG_LOG_PATH = PROJECT_ROOT / "dados" / "apim_debug.jsonl"

RETRYABLE_STATUS_CODES = {
    408,  # Request Timeout
    409,  # Alguns gateways usam 409 temporariamente
    425,  # Too Early
    429,  # Rate limit
}


def _get_api_key(cfg: dict) -> str:
    return (cfg.get("api_key") or API_KEY or "").strip()


def _safe_int(value, default: int, minimum: int = 1, maximum: int = 20) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _safe_float(
    value,
    default: float,
    minimum: float = 0.0,
    maximum: float = 3600.0,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _optional_float(value):
    text = str(value if value is not None else "").strip().lower()
    if text in {"", "none", "null", "false", "off"}:
        return None
    return float(text)


def _optional_int(value):
    text = str(value if value is not None else "").strip().lower()
    if text in {"", "none", "null", "false", "off"}:
        return None
    return int(text)


def _build_verify_option(cfg: dict, *, default: bool = True):
    ca_cert_val = str(cfg.get("ca_cert", "")).strip()

    if ca_cert_val.lower() == "false":
        return False

    if ca_cert_val:
        ca_cert_path = Path(ca_cert_val).expanduser()
        if not ca_cert_path.is_file():
            raise RuntimeError(
                "Certificado corporativo inválido: o caminho informado não "
                f"existe ou não é arquivo: {ca_cert_val}. Deixe o campo em "
                "branco para usar os certificados padrão do sistema, use "
                "'false' apenas para desabilitar a validação TLS em ambiente "
                "local/teste, ou informe o caminho completo de um CA bundle "
                "válido."
            )
        return str(ca_cert_path)

    return default


def _join_chat_completions_url(api_base: str) -> str:
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _extract_message_content(data: dict) -> str:
    choices = data.get("choices")

    if not choices:
        raise RuntimeError(
            "O servidor respondeu com sucesso (HTTP 200), mas não trouxe "
            f"'choices'. Resposta bruta: {_truncate(str(data), 3000)}"
        )

    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        partes = []

        for item in content:
            if isinstance(item, dict):
                texto = item.get("text") or item.get("content")
                if isinstance(texto, str):
                    partes.append(texto)
            elif isinstance(item, str):
                partes.append(item)

        if partes:
            return "\n".join(partes)

    raise RuntimeError(
        "O servidor respondeu com sucesso (HTTP 200), mas o conteúdo da "
        "mensagem veio vazio ou em formato não suportado. "
        f"Resposta bruta: {_truncate(str(data), 3000)}"
    )


def _build_chat_request(
    cfg: dict,
) -> tuple[str, str, dict, dict, dict, object]:
    provider = str(cfg.get("api_provider", "azure")).lower().strip()
    api_key = _get_api_key(cfg)

    # Não registrar este dicionário: ele contém a credencial.
    headers = {}
    params = {}
    body = {
        "messages": [],
    }

    temperature = _optional_float(cfg.get("temperature"))
    if temperature is not None:
        body["temperature"] = temperature

    max_tokens = _optional_int(cfg.get("max_tokens"))
    if max_tokens is not None:
        body["max_tokens"] = max_tokens

    if provider == "azure":
        if not api_key:
            raise RuntimeError(
                "Token/API key não definido nas Configurações nem no .env"
            )

        api_base = str(cfg.get("api_base") or "").strip()
        deployment_id = str(cfg.get("deployment_id") or "").strip()
        api_version = str(cfg.get("api_version") or "").strip()

        if not api_base:
            raise RuntimeError("api_base não configurada.")
        if not deployment_id:
            raise RuntimeError("deployment_id não configurado.")
        if not api_version:
            raise RuntimeError("api_version não configurada.")

        url = (
            f"{api_base.rstrip('/')}/deployments/"
            f"{quote(deployment_id)}/chat/completions"
        )
        params = {"api-version": api_version}
        headers["api-key"] = api_key

        verify_opt = _build_verify_option(cfg, default=True)
        return provider, url, params, headers, body, verify_opt

    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        if provider in {"gemini", "google"} and not api_key:
            raise RuntimeError(
                "Token/API key não definido nas Configurações nem no .env "
                "para usar a API Gemini"
            )

        api_base = str(cfg.get("api_base") or "").strip()
        if not api_base:
            raise RuntimeError("api_base não configurada.")

        url = _join_chat_completions_url(api_base)

        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        model = str(
            cfg.get("model")
            or cfg.get("deployment_id")
            or ""
        ).strip()

        if not model:
            raise RuntimeError(
                "Modelo não configurado. Defina model ou deployment_id."
            )

        body["model"] = model
        verify_opt = _build_verify_option(cfg, default=True)
        return provider, url, params, headers, body, verify_opt

    raise RuntimeError(
        f"Provedor de API desconhecido: {provider}. "
        "Use 'azure', 'openai' ou 'gemini'."
    )


def _truncate(text: str, limit: int = 1500) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit] + "... [cortado]"


def _message_summary(messages: list) -> list[dict]:
    summary = []

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            summary.append({
                "index": index,
                "role": "invalido",
                "chars": len(str(message)),
            })
            continue

        content = message.get("content", "")

        if isinstance(content, str):
            chars = len(content)
        else:
            try:
                chars = len(
                    json.dumps(
                        content,
                        ensure_ascii=False,
                        default=str,
                    )
                )
            except Exception:
                chars = len(str(content))

        summary.append({
            "index": index,
            "role": str(message.get("role") or ""),
            "chars": chars,
        })

    return summary


def _payload_metrics(body: dict) -> dict:
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    messages = body.get("messages") or []

    return {
        "payload_bytes": len(encoded),
        "message_count": len(messages),
        "messages": _message_summary(messages),
    }


def _response_metadata(response: httpx.Response) -> dict:
    headers = response.headers

    request_id = (
        headers.get("apim-request-id")
        or headers.get("x-request-id")
        or headers.get("x-ms-request-id")
        or headers.get("request-id")
        or headers.get("x-correlation-id")
    )

    return {
        "status": response.status_code,
        "request_id": request_id,
        "retry_after": headers.get("retry-after"),
        "ratelimit_limit_requests": (
            headers.get("x-ratelimit-limit-requests")
            or headers.get("ratelimit-limit")
        ),
        "ratelimit_remaining_requests": (
            headers.get("x-ratelimit-remaining-requests")
            or headers.get("ratelimit-remaining")
        ),
        "ratelimit_reset_requests": (
            headers.get("x-ratelimit-reset-requests")
            or headers.get("ratelimit-reset")
        ),
        "ratelimit_limit_tokens": headers.get(
            "x-ratelimit-limit-tokens"
        ),
        "ratelimit_remaining_tokens": headers.get(
            "x-ratelimit-remaining-tokens"
        ),
        "ratelimit_reset_tokens": headers.get(
            "x-ratelimit-reset-tokens"
        ),
        "region": (
            headers.get("x-ms-region")
            or headers.get("azureml-model-session")
        ),
        "server": headers.get("server"),
    }


def _append_debug_event(event: dict) -> None:
    """
    Registra somente metadados técnicos.

    Não grava API key, Authorization, prompts nem respostas completas.
    """
    try:
        DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            **event,
        }

        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )
    except Exception as log_error:
        print(
            f"[APIM DEBUG] Falha ao gravar {DEBUG_LOG_PATH}: "
            f"{log_error}",
            flush=True,
        )


def _print_event(event: dict) -> None:
    compact = {
        key: value
        for key, value in event.items()
        if key != "messages"
    }

    print(
        "[APIM] "
        + json.dumps(
            compact,
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )


def _log_event(event: dict) -> None:
    _print_event(event)
    _append_debug_event(event)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None

    text = value.strip()

    try:
        seconds = float(text)
        return max(0.0, min(seconds, 300.0))
    except ValueError:
        pass

    try:
        retry_date = parsedate_to_datetime(text)
        if retry_date.tzinfo is None:
            retry_date = retry_date.replace(tzinfo=timezone.utc)

        seconds = (
            retry_date.astimezone(timezone.utc)
            - datetime.now(timezone.utc)
        ).total_seconds()

        return max(0.0, min(seconds, 300.0))
    except (TypeError, ValueError, OverflowError):
        return None


def _retry_delay(
    attempt: int,
    base_seconds: float,
    response: httpx.Response | None = None,
) -> float:
    if response is not None:
        retry_after = _parse_retry_after(
            response.headers.get("retry-after")
        )
        if retry_after is not None:
            return retry_after

    exponential = base_seconds * (2 ** max(0, attempt - 1))
    jitter = random.uniform(0.0, min(1.0, base_seconds))
    return min(exponential + jitter, 60.0)


def _http_error_message(
    *,
    provider: str,
    url: str,
    attempt: int,
    max_attempts: int,
    response: httpx.Response,
    metrics: dict,
    elapsed_seconds: float,
    client_request_id: str,
) -> str:
    metadata = _response_metadata(response)

    return (
        f"Erro HTTP {response.status_code} ao chamar o provedor '{provider}'. "
        f"Tentativa {attempt}/{max_attempts}. "
        f"Duração: {elapsed_seconds:.2f}s. "
        f"Client request ID: {client_request_id}. "
        f"Server request ID: {metadata.get('request_id') or 'não informado'}. "
        f"Retry-After: {metadata.get('retry_after') or 'não informado'}. "
        "Remaining requests: "
        f"{metadata.get('ratelimit_remaining_requests') or 'não informado'}. "
        "Remaining tokens: "
        f"{metadata.get('ratelimit_remaining_tokens') or 'não informado'}. "
        f"Payload: {metrics['payload_bytes']} bytes em "
        f"{metrics['message_count']} mensagens. "
        f"URL: {url}. "
        f"Resposta: {_truncate(response.text, 2000)}"
    )


async def _call_chat_messages_serialized(
    cfg: dict,
    messages: list,
) -> str:
    provider, url, params, headers, body, verify_opt = (
        _build_chat_request(cfg)
    )
    body["messages"] = messages

    metrics = _payload_metrics(body)
    max_attempts = _safe_int(
        cfg.get("api_max_tentativas"),
        default=3,
        minimum=1,
        maximum=8,
    )
    retry_base_seconds = _safe_float(
        cfg.get("api_retry_base_seconds"),
        default=2.0,
        minimum=0.25,
        maximum=60.0,
    )

    timeout = httpx.Timeout(
        connect=_safe_float(
            cfg.get("api_timeout_connect"),
            default=150.0,
            minimum=1.0,
            maximum=900.0,
        ),
        read=_safe_float(
            cfg.get("api_timeout_read"),
            default=900.0,
            minimum=1.0,
            maximum=3600.0,
        ),
        write=_safe_float(
            cfg.get("api_timeout_write"),
            default=300.0,
            minimum=1.0,
            maximum=1800.0,
        ),
        pool=_safe_float(
            cfg.get("api_timeout_pool"),
            default=300.0,
            minimum=1.0,
            maximum=1800.0,
        ),
    )

    client_request_id = str(uuid4())

    # Identificador seguro para correlação. Não é credencial.
    request_headers = dict(headers)
    request_headers["x-client-request-id"] = client_request_id
    request_headers["x-ms-client-request-id"] = client_request_id

    start_event = {
        "event": "request_start",
        "client_request_id": client_request_id,
        "provider": provider,
        "url": url,
        "max_attempts": max_attempts,
        **metrics,
    }
    _log_event(start_event)

    last_exception: Exception | None = None

    async with httpx.AsyncClient(
        verify=verify_opt,
        timeout=timeout,
    ) as client:
        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            response: httpx.Response | None = None

            try:
                response = await client.post(
                    url,
                    params=params,
                    headers=request_headers,
                    json=body,
                )
                elapsed = time.perf_counter() - started
                metadata = _response_metadata(response)

                response_event = {
                    "event": "response",
                    "client_request_id": client_request_id,
                    "provider": provider,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "elapsed_seconds": round(elapsed, 3),
                    **metrics,
                    **metadata,
                    "response_preview": _truncate(
                        response.text,
                        1000,
                    ),
                }
                _log_event(response_event)

                if 200 <= response.status_code <= 299:
                    try:
                        data = response.json()
                    except (json.JSONDecodeError, ValueError) as error:
                        raise RuntimeError(
                            "O provedor respondeu HTTP "
                            f"{response.status_code}, mas o corpo não é JSON "
                            f"válido. Client request ID: {client_request_id}. "
                            f"Server request ID: "
                            f"{metadata.get('request_id') or 'não informado'}. "
                            f"Resposta: {_truncate(response.text, 2000)}"
                        ) from error

                    result = _extract_message_content(data)

                    _log_event({
                        "event": "request_success",
                        "client_request_id": client_request_id,
                        "provider": provider,
                        "attempt": attempt,
                        "elapsed_seconds": round(elapsed, 3),
                        "response_chars": len(result),
                        **metrics,
                        **metadata,
                    })

                    return result

                error_message = _http_error_message(
                    provider=provider,
                    url=url,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    response=response,
                    metrics=metrics,
                    elapsed_seconds=elapsed,
                    client_request_id=client_request_id,
                )

                retryable = (
                    response.status_code in RETRYABLE_STATUS_CODES
                    or 500 <= response.status_code <= 599
                )

                http_error = httpx.HTTPStatusError(
                    error_message,
                    request=response.request,
                    response=response,
                )
                last_exception = http_error

                # 400, 401, 403, 404, 422 etc. não melhoram com retry.
                if not retryable:
                    _log_event({
                        "event": "request_failed_non_retryable",
                        "client_request_id": client_request_id,
                        "provider": provider,
                        "attempt": attempt,
                        **metrics,
                        **metadata,
                        "error": _truncate(error_message, 3000),
                    })
                    raise http_error

                if attempt >= max_attempts:
                    _log_event({
                        "event": "request_failed_retries_exhausted",
                        "client_request_id": client_request_id,
                        "provider": provider,
                        "attempt": attempt,
                        **metrics,
                        **metadata,
                        "error": _truncate(error_message, 3000),
                    })
                    raise http_error

                delay = _retry_delay(
                    attempt,
                    retry_base_seconds,
                    response,
                )

                _log_event({
                    "event": "retry_scheduled",
                    "client_request_id": client_request_id,
                    "provider": provider,
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "delay_seconds": round(delay, 3),
                    **metrics,
                    **metadata,
                })

                await asyncio.sleep(delay)

            except httpx.HTTPStatusError:
                raise

            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ReadError,
                httpx.WriteError,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
            ) as error:
                elapsed = time.perf_counter() - started
                last_exception = error

                _log_event({
                    "event": "network_error",
                    "client_request_id": client_request_id,
                    "provider": provider,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "elapsed_seconds": round(elapsed, 3),
                    "error_type": type(error).__name__,
                    "error": _truncate(str(error), 2000),
                    **metrics,
                })

                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"Falha de rede após {max_attempts} tentativas. "
                        f"Client request ID: {client_request_id}. "
                        f"Tipo: {type(error).__name__}. "
                        f"Detalhe: {error}. "
                        f"Payload: {metrics['payload_bytes']} bytes em "
                        f"{metrics['message_count']} mensagens."
                    ) from error

                delay = _retry_delay(
                    attempt,
                    retry_base_seconds,
                    None,
                )

                _log_event({
                    "event": "retry_scheduled",
                    "client_request_id": client_request_id,
                    "provider": provider,
                    "attempt": attempt,
                    "next_attempt": attempt + 1,
                    "delay_seconds": round(delay, 3),
                    "reason": type(error).__name__,
                    **metrics,
                })

                await asyncio.sleep(delay)

    raise RuntimeError(
        "Falha inesperada ao chamar a API. "
        f"Client request ID: {client_request_id}. "
        f"Última exceção: {last_exception}"
    )


async def call_chat_messages(cfg: dict, messages: list) -> str:
    """
    Chama o modelo com uma requisição por vez dentro deste processo.

    O diagnóstico sanitizado é gravado em:
        dados/apim_debug.jsonl

    Campos opcionais aceitos em config_kv:
        api_max_tentativas
        api_retry_base_seconds
        api_timeout_connect
        api_timeout_read
        api_timeout_write
        api_timeout_pool

    Para omitir temperature ou max_tokens, deixe o valor vazio.
    """
    if not isinstance(messages, list) or not messages:
        raise ValueError(
            "messages deve ser uma lista não vazia."
        )

    waiting_started = time.perf_counter()

    async with MODEL_SEMAPHORE:
        queue_seconds = time.perf_counter() - waiting_started

        _log_event({
            "event": "semaphore_acquired",
            "queue_seconds": round(queue_seconds, 3),
            "pending_note": (
                "Valor alto indica concorrência entre chat, agenda, "
                "Telegram, Discord ou outras chamadas no mesmo processo."
            ),
        })

        return await _call_chat_messages_serialized(
            cfg,
            messages,
        )
