import asyncio
import inspect
from datetime import datetime
from app.db import get_all_tasks, get_config, get_conn

DISPAROS_REALIZADOS: set[str] = set()
JOBS_EM_ANDAMENTO: set[asyncio.Task] = set()
_JOB_SEMAPHORE: asyncio.Semaphore | None = None
_JOB_SEMAPHORE_LIMIT: int | None = None


def _safe_int(value, default: int, minimum: int = 1, maximum: int = 100) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _safe_float(value, default: float, minimum: float = 0.1, maximum: float = 3600.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))


def _optional_positive_float(value, maximum: float = 24 * 3600.0) -> float | None:
    text = str(value if value is not None else "").strip().lower()
    if text in {"", "0", "none", "null", "false", "off", "sem", "sem timeout"}:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return min(parsed, maximum)


def _get_job_semaphore(limit: int) -> asyncio.Semaphore:
    global _JOB_SEMAPHORE, _JOB_SEMAPHORE_LIMIT
    if _JOB_SEMAPHORE is None or _JOB_SEMAPHORE_LIMIT != limit:
        _JOB_SEMAPHORE = asyncio.Semaphore(limit)
        _JOB_SEMAPHORE_LIMIT = limit
    return _JOB_SEMAPHORE


def _track_background_job(task: asyncio.Task) -> None:
    JOBS_EM_ANDAMENTO.add(task)
    task.add_done_callback(JOBS_EM_ANDAMENTO.discard)


def update_heartbeat(status: str):
    """Atualiza um log rápido no banco para provar que o sistema não travou"""
    with get_conn() as c:
        c.execute(
            "INSERT INTO config_kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            ("ultimo_scan_watchdog", f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {status}")
        )
        c.commit()


def _normalizar_horario_fixo(regra: str) -> str | None:
    partes = regra.split(":")
    if len(partes) != 2:
        return None

    try:
        hora = int(partes[0])
        minuto = int(partes[1])
    except ValueError:
        return None

    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None

    return f"{hora:02d}:{minuto:02d}"


def _deve_executar_regra(task_id: int, regra: str, agora: datetime) -> bool:
    regra = regra.strip()
    minuto_key = agora.strftime("%Y-%m-%d %H:%M")
    agora_str = agora.strftime("%H:%M")

    if regra.startswith("*/") and regra.endswith("m"):
        try:
            intervalo = int(regra.replace("*/", "").replace("m", ""))
        except ValueError:
            return False

        if intervalo <= 0 or agora.minute % intervalo != 0:
            return False

        chave = f"{task_id}:{regra}:{minuto_key}"
        if chave in DISPAROS_REALIZADOS:
            return False
        DISPAROS_REALIZADOS.add(chave)
        return True

    horario_fixo = _normalizar_horario_fixo(regra)
    if horario_fixo != agora_str:
        return False

    chave = f"{task_id}:{horario_fixo}:{minuto_key}"
    if chave in DISPAROS_REALIZADOS:
        return False
    DISPAROS_REALIZADOS.add(chave)
    return True


def _limpar_disparos_antigos(agora: datetime):
    hoje = agora.strftime("%Y-%m-%d")
    antigos = {chave for chave in DISPAROS_REALIZADOS if hoje not in chave}
    DISPAROS_REALIZADOS.difference_update(antigos)


def _avaliar_condicao_sync(t: dict) -> tuple[bool, str]:
    prompt_final = t["prompt"]
    script = t.get("condition_script")
    if not script:
        return True, prompt_final

    local_scope = {}
    exec(script, local_scope, local_scope)
    avaliar = local_scope.get("avaliar")
    if not callable(avaliar):
        return True, prompt_final

    resultado = avaliar()
    if not resultado:
        return False, prompt_final
    if isinstance(resultado, str):
        prompt_final = (
            "ALERTA DO SISTEMA DE GATILHO:\n"
            f"{resultado}\n\nCOMANDO ORIGINAL:\n{t['prompt']}"
        )
    return True, prompt_final


async def avaliar_condicao_task(
    t: dict,
    timeout_seconds: float | None = None,
) -> tuple[bool, str]:
    """Executa gatilhos Python fora do event loop para não travar a UI.

    Por padrão não corta processos demorados: eles terminam no background.
    Timeout só é aplicado se configurado com valor positivo.
    """
    try:
        evaluation = asyncio.to_thread(_avaliar_condicao_sync, t)
        if timeout_seconds is None:
            return await evaluation
        return await asyncio.wait_for(evaluation, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        print(
            f"Gatilho Python '{t['title']}' excedeu {timeout_seconds:.1f}s; "
            "pulando disparo por timeout configurado.",
            flush=True,
        )
    except Exception as e:
        print(f"Erro no script '{t['title']}': {e}", flush=True)
    return False, t["prompt"]


async def disparar_maestro_local(titulo: str, prompt: str, cfg: dict | None = None):
    """Dispara o Maestro internamente, sem API HTTP padrão."""
    cfg = cfg or get_config()
    max_jobs = _safe_int(cfg.get("scheduler_max_concurrent_jobs"), default=1, minimum=1, maximum=20)
    timeout_seconds = _optional_positive_float(
        cfg.get("scheduler_maestro_hard_timeout_seconds")
    )
    semaphore = _get_job_semaphore(max_jobs)

    async with semaphore:
        try:
            from app.core import processar_orquestracao

            coro = processar_orquestracao(
                mensagem=prompt,
                origem=f"AGENDA: {titulo}",
            )
            if timeout_seconds is None:
                await coro
            else:
                await asyncio.wait_for(coro, timeout=timeout_seconds)
        except Exception as e:
            print(f"Erro ao chamar Maestro local: {e}", flush=True)


async def despachar_evento_agenda(
    titulo: str,
    prompt: str,
    cfg: dict,
    agora_str: str,
) -> None:
    dispatch_code = (cfg.get("scheduler_dispatch_code") or "").strip()
    if dispatch_code:
        payload = _montar_payload_agenda(titulo, prompt, agora_str)
        await _executar_dispatch_agenda_customizado(dispatch_code, payload, cfg)
        return

    print(
        f"Agenda '{titulo}' ignorada: scheduler_dispatch_code não configurado.",
        flush=True,
    )


def _montar_payload_agenda(titulo: str, prompt: str, agora_str: str) -> dict:
    return {
        "tipo": "agenda",
        "origem": f"AGENDA: {titulo}",
        "titulo": titulo,
        "prompt": prompt,
        "horario_scan": agora_str,
    }


async def _executar_dispatch_agenda_customizado(
    dispatch_code: str,
    evento: dict,
    cfg: dict,
) -> None:
    async def chamar_maestro(mensagem: str | None = None, origem: str | None = None):
        from app.core import processar_orquestracao

        return await processar_orquestracao(
            mensagem=mensagem or evento.get("prompt", ""),
            origem=origem or evento.get("origem", "AGENDA"),
        )

    async def chamar_hook(slug: str, payload: dict | None = None, headers: dict | None = None):
        from app.routers.hooks import dispatch_hook

        return await dispatch_hook(
            slug,
            payload or evento,
            headers or {"x-agente-origem": "agenda"},
        )

    scope = {
        "asyncio": asyncio,
        "get_config": get_config,
        "disparar_maestro_local": disparar_maestro_local,
    }
    helpers = {
        "processar_orquestracao": chamar_maestro,
        "dispatch_hook": chamar_hook,
        "disparar_maestro_local": lambda titulo, prompt: disparar_maestro_local(titulo, prompt, cfg),
        "montar_payload_agenda": _montar_payload_agenda,
    }

    try:
        exec(dispatch_code, scope, scope)
        func = (
            scope.get("despachar_agenda")
            or scope.get("despachar_evento_agenda")
            or scope.get("despachar")
            or scope.get("executar")
        )
        if not callable(func):
            raise RuntimeError(
                "Def customizada sem função de entrada. Use despachar_agenda(evento, cfg, helpers), "
                "despachar_evento_agenda(titulo, prompt, cfg, agora_str) ou executar(...)."
            )

        assinatura = inspect.signature(func)
        parametros = assinatura.parameters
        if "evento" in parametros:
            resultado = func(evento, cfg, helpers)
        elif len(parametros) >= 4:
            resultado = func(
                evento.get("titulo", ""),
                evento.get("prompt", ""),
                cfg,
                evento.get("horario_scan", ""),
            )
        elif len(parametros) == 3:
            resultado = func(evento, cfg, helpers)
        else:
            resultado = func(evento)
        if inspect.isawaitable(resultado):
            await resultado
    except Exception as exc:
        print(f"Erro no dispatch customizado da agenda: {exc}", flush=True)


async def processar_tarefa_agendada(
    t: dict,
    cfg: dict,
    agora_str: str,
) -> None:
    condition_timeout = _optional_positive_float(
        cfg.get("scheduler_condition_hard_timeout_seconds")
    )
    condicao_valida, prompt_final = await avaliar_condicao_task(
        t,
        timeout_seconds=condition_timeout,
    )

    if not condicao_valida:
        return

    destino = (cfg.get("scheduler_default_hook_slug") or "Maestro direto").strip()
    print(f"[{agora_str}] 🚀 Disparando Tarefa: '{t['title']}' via {destino}!")
    await despachar_evento_agenda(t["title"], prompt_final, cfg, agora_str)


async def start_periodic_scheduler():
    """Loop infinito do Relógio. Avalia os gatilhos e delega para a API."""
    print("Motor de Agendamento iniciado. (Agora isolando gatilhos pesados do event loop)")
    while True:
        agora = datetime.now()
        agora_str = agora.strftime("%H:%M")
        _limpar_disparos_antigos(agora)

        teve_anomalia = False

        try:
            cfg = get_config()
            tarefas = get_all_tasks()
            for t in tarefas:
                if t["active"] == 1:
                    regras = [r.strip() for r in t["schedule_hours"].split(",") if r.strip()]
                    deve_executar_tempo = any(
                        _deve_executar_regra(t["id"], regra, agora)
                        for regra in regras
                    )

                    if deve_executar_tempo:
                        # O relógio só enfileira. A condição e o Maestro rodam no background.
                        teve_anomalia = True
                        job = asyncio.create_task(processar_tarefa_agendada(t, cfg, agora_str))
                        _track_background_job(job)

            # Atualiza o Heartbeat Visual
            backlog = len(JOBS_EM_ANDAMENTO)
            if not teve_anomalia:
                update_heartbeat(f"Nenhuma anomalia detectada (Status: OK, scan {agora_str}, jobs agenda: {backlog})")
            else:
                update_heartbeat(f"⚠️ Anomalia enviada para IA! (scan {agora_str}, jobs agenda: {backlog})")

        except Exception as e:
            print(f"Erro no Worker: {e}")
            update_heartbeat(f"🚨 ERRO NO WATCHDOG GERAL: {str(e)}")

        agora_sleep = datetime.now()
        segundos_restantes = 60 - agora_sleep.second
        await asyncio.sleep(max(1, segundos_restantes))
