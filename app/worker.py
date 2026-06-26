import asyncio
import httpx
from datetime import datetime
from app.db import get_all_tasks, get_config, get_conn

DISPAROS_REALIZADOS: set[str] = set()


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


async def disparar_maestro_api(titulo: str, prompt: str):
    """Usa a API OpenAI compatível do Maestro local com token obrigatório."""
    url = "http://127.0.0.1:8000/api/maestro"
    cfg = get_config()
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
        # Timeout longo caso queira aguentar a requisição inteira, mas rodará em Task isolada
        async with httpx.AsyncClient(timeout=300.0) as client:
            await client.post(url, headers=headers, json=payload)
    except Exception as e:
        print(f"Erro ao chamar API Central do Maestro: {e}")


async def start_periodic_scheduler():
    """Loop infinito do Relógio. Avalia os gatilhos e delega para a API."""
    print("Motor de Agendamento iniciado. (Agora usando API Centralizada)")
    while True:
        agora = datetime.now()
        agora_str = agora.strftime("%H:%M")
        _limpar_disparos_antigos(agora)

        teve_anomalia = False

        try:
            tarefas = get_all_tasks()
            for t in tarefas:
                if t["active"] == 1:
                    regras = [r.strip() for r in t["schedule_hours"].split(",") if r.strip()]
                    deve_executar_tempo = any(
                        _deve_executar_regra(t["id"], regra, agora)
                        for regra in regras
                    )

                    if deve_executar_tempo:
                        prompt_final = t["prompt"]
                        condicao_valida = True

                        if t.get("condition_script"):
                            local_scope = {}
                            try:
                                exec(t["condition_script"], {}, local_scope)
                                if "avaliar" in local_scope:
                                    resultado = local_scope["avaliar"]()

                                    if not resultado:
                                        condicao_valida = False
                                    elif isinstance(resultado, str):
                                        prompt_final = f"ALERTA DO SISTEMA DE GATILHO:\n{resultado}\n\nCOMANDO ORIGINAL:\n{t['prompt']}"
                            except Exception as e:
                                print(f"Erro no script '{t['title']}': {e}")
                                condicao_valida = False

                        # O RELÓGIO APENAS CHAMA A API ASSÍNCRONA!
                        if condicao_valida:
                            print(f"[{agora_str}] 🚀 Disparando Tarefa: '{t['title']}' via API Central!")
                            teve_anomalia = True
                            asyncio.create_task(disparar_maestro_api(t["title"], prompt_final))

            # Atualiza o Heartbeat Visual
            if not teve_anomalia:
                update_heartbeat(f"Nenhuma anomalia detectada (Status: OK, scan {agora_str})")
            else:
                update_heartbeat(f"⚠️ Anomalia enviada para IA! (scan {agora_str})")

        except Exception as e:
            print(f"Erro no Worker: {e}")
            update_heartbeat(f"🚨 ERRO NO WATCHDOG GERAL: {str(e)}")

        agora_sleep = datetime.now()
        segundos_restantes = 60 - agora_sleep.second
        await asyncio.sleep(max(1, segundos_restantes))
