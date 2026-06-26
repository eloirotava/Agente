import asyncio
import httpx
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


async def disparar_maestro_api(titulo: str, prompt: str, cfg: dict | None = None):
    """Usa a API OpenAI compatível do Maestro local com token obrigatório."""
    cfg = cfg or get_config()
    max_jobs = _safe_int(cfg.get("scheduler_max_concurrent_jobs"), default=1, minimum=1, maximum=20)
    timeout_seconds = _optional_positive_float(
        cfg.get("scheduler_maestro_hard_timeout_seconds")
    )
    semaphore = _get_job_semaphore(max_jobs)

    async with semaphore:
        url = "http://127.0.0.1:8081/api/maestro"
        token = (cfg.get("maestro_api_token") or "").strip()
        if not token:
            print("Erro ao chamar API Central do Maestro: token local do Maestro não configurado.")
            return

        payload = {
            "model": "botmig-maestro",
            "origem": f"AGENDA: {titulo}",
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except Exception as e:
            print(f"Erro ao chamar API Central do Maestro: {e}", flush=True)


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

    print(f"[{agora_str}] 🚀 Disparando Tarefa: '{t['title']}' via API Central!")
    await disparar_maestro_api(t["title"], prompt_final, cfg)


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
