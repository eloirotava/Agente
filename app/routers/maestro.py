import json
import asyncio
import traceback  # Rastreio completo de erros
from typing import Any, List, Tuple

from fastapi import APIRouter

from app.db import (
    get_config,
    get_context,
    get_general_contexts,
    get_tool,
    get_all_tools,
    log_interaction,
    get_latest_endpoint_version_number,
)
from app.llm_gateway import call_llm_messages, config_fingerprint

router = APIRouter()

MAX_ERROS_FORMATO_CONSECUTIVOS = 3

def _parse_json_sequence(text: str) -> Tuple[List[Any], str]:
    decoder = json.JSONDecoder()
    s = (text or "").strip()
    values: List[Any] = []
    idx = 0

    while idx < len(s):
        while idx < len(s) and s[idx].isspace():
            idx += 1
        if idx >= len(s):
            break
        try:
            obj, end = decoder.raw_decode(s, idx)
        except json.JSONDecodeError:
            return values, s[idx:]
        values.append(obj)
        idx = end
    return values, ""

def _remover_cercas_markdown_json(text: str) -> str:
    s = (text or "").strip()

    if s.startswith("```"):
        partes = s.split("\n", 1)
        s = partes[1] if len(partes) > 1 else ""

    if s.rstrip().endswith("```"):
        s = s.rstrip()[:-3]

    return s.strip()


def _limpar_resposta_modelo_para_json(text: str) -> str:
    s = _remover_cercas_markdown_json(text)

    while True:
        s_strip = s.lstrip()
        lowered = s_strip.lower()
        if lowered.startswith("<thought>") or lowered.startswith("<think>"):
            tag = "thought" if lowered.startswith("<thought>") else "think"
            fim = lowered.find(f"</{tag}>")
            if fim == -1:
                break
            s = _remover_cercas_markdown_json(
                s_strip[fim + len(f"</{tag}>"):]
            )
            continue
        break

    primeiro_objeto = s.find("{")
    primeira_lista = s.find("[")
    candidatos = [idx for idx in (primeiro_objeto, primeira_lista) if idx != -1]
    if candidatos:
        primeiro_json = min(candidatos)
        if primeiro_json > 0:
            s = s[primeiro_json:].strip()

    return _remover_cercas_markdown_json(s)

def _protocolo_json_reenvio_msg() -> str:
    return (
        "ERRO DE FORMATO (PROTOCOLO JSON): Sua última mensagem não seguiu o protocolo.\n"
        "Reenvie AGORA como EXATAMENTE UM ÚNICO JSON válido, sem qualquer texto fora do JSON.\n"
        "Escolha APENAS UMA opção:\n"
        "1) Lista JSON (array) de ações: começa com '[' e termina com ']'.\n"
        "2) Objeto JSON final: {\"acao\":\"responder\",\"resposta\":\"...\"} (começa com '{' e termina com '}').\n"
        "PROIBIDO: dois JSONs na mesma mensagem (ex: [...] {...} ou [...] [...]), repetir o JSON, adicionar texto fora do JSON ou usar tags <thought>/<think>."
    )

def _truncate(text: str, limit: int = 8000) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n... [TEXTO CORTADO POR LIMITE DE TOKENS]"

async def _executar_comandos_maestro(comandos_lista: List[dict]) -> Tuple[str, List[str]]:
    logs_exec: List[str] = []
    respostas_acumuladas: List[str] = []

    for cmd in comandos_lista:
        if not isinstance(cmd, dict):
            respostas_acumuladas.append("SISTEMA: Erro. Item da lista de comandos não é objeto JSON.")
            continue

        acao = cmd.get("acao", "")

        if acao == "responder":
            respostas_acumuladas.append("SISTEMA: Erro. 'responder' é proibido dentro de uma lista de ações.")
            continue

        if acao in ["ler_contexto", "pedir_manual", "buscar_manual"]:
            slug = cmd.get("slug", "")
            dados = get_context(slug)
            texto = dados.get("content") if dados else None

            if not texto:
                dados_ferramenta = get_tool(slug)
                if dados_ferramenta:
                    texto = dados_ferramenta.get("tool_context")

            if texto:
                respostas_acumuladas.append(f"SISTEMA: Conteúdo técnico de '{slug}':\n{texto}")
            else:
                respostas_acumuladas.append(f"SISTEMA: Erro. Endpoint ou contexto de '{slug}' não encontrado.")
        else:
            tool = get_tool(acao)
            if tool and tool.get("content"):
                try:
                    local_scope = {}
                    exec(tool["content"], {}, local_scope)

                    if "executar" in local_scope:
                        resultado = await asyncio.to_thread(local_scope["executar"], cmd)
                        respostas_acumuladas.append(f"SISTEMA (Resultado '{acao}'):\n{resultado}")
                    else:
                        respostas_acumuladas.append(f"SISTEMA: Erro. Script '{acao}' sem a função 'executar'.")
                except Exception as e:
                    respostas_acumuladas.append(f"SISTEMA: Erro ao executar script '{acao}': {str(e)}")
            else:
                respostas_acumuladas.append(f"SISTEMA: Erro. Endpoint Python '{acao}' desconhecido.")

    texto_devolucao = "\n\n----------------------------------------\n\n".join(respostas_acumuladas)
    logs_exec.append(f"EXECUÇÃO DE ENDPOINTS ({len(comandos_lista)} comandos):\n{texto_devolucao}")
    return texto_devolucao, logs_exec

async def processar_orquestracao(mensagem: str, origem: str):
    cfg = get_config()
    ctx_base = get_context("system_prompt")
    system_prompt = ctx_base["content"] if ctx_base else "Você é um assistente."

    system_version = get_latest_endpoint_version_number("context", "system_prompt") or "?"
    resource_versions = [f"context:system_prompt@v{system_version}"]

    recursos_disponiveis = "\n\nRECURSOS DISPONÍVEIS:"
    tem_recurso = False

    for m in get_general_contexts():
        resource_versions.append(
            f"context:{m['slug']}@v{get_latest_endpoint_version_number('context', m['slug']) or '?'}"
        )
        if m.get("description_for_ai"):
            tem_recurso = True
            recursos_disponiveis += f"\n- Endpoint manual '{m['title']}': {m['description_for_ai']}"

    for t in get_all_tools():
        resource_versions.append(
            f"tool:{t['slug']}@v{get_latest_endpoint_version_number('tool', t['slug']) or '?'}"
        )
        if t.get("description_for_ai"):
            tem_recurso = True
            recursos_disponiveis += f"\n- Endpoint Python '{t['title']}': {t['description_for_ai']}"

    if tem_recurso:
        system_prompt += recursos_disponiveis

    system_prompt += (
        "\n\nREGRA DE EXECUÇÃO EM LOTE: Você pode invocar múltiplos recursos de uma vez só se precisar de várias informações. "
        "Para fazer chamadas múltiplas, envie uma lista JSON de objetos, por exemplo:\n"
        "[{\"acao\": \"ler_contexto\", \"slug\": \"tags_pi\"}, {\"acao\": \"ler_pagina_web\", \"url\": \"...\"}]\n"
        "Quando tiver dados suficientes para responder, gere a resposta final OBRIGATORIAMENTE no formato JSON de objeto único: "
        "{\"acao\": \"responder\", \"resposta\": \"Sua resposta final aqui\"}"
    )

    mensagens: List[dict] = [
        {"role": "system", "content": system_prompt},
    ]

    log_raciocinio: List[str] = []
    log_raciocinio.append(f"[ORIGEM: {origem}]")
    log_raciocinio.append(f"MENSAGEM DO USUÁRIO:\n{mensagem}")
    log_raciocinio.append(f"SYSTEM PROMPT INJETADO (Tamanho: {len(system_prompt)} caracteres)")
    log_raciocinio.append(f"LLM CONFIG FINGERPRINT: {config_fingerprint(cfg)}")
    log_raciocinio.append("VERSÕES DOS RECURSOS: " + ", ".join(resource_versions))

    bootstrap_json = ""
    if ctx_base and isinstance(ctx_base, dict):
        bootstrap_json = (ctx_base.get("bootstrap_json") or "").strip()

    if bootstrap_json:
        log_raciocinio.append("BOOTSTRAP: Executando pré-ações.")
        try:
            parsed = json.loads(bootstrap_json)
            comandos_boot: List[dict] = []
            for item in parsed:
                if isinstance(item, dict) and item.get("acao") != "responder":
                    comandos_boot.append(item)

            texto_boot, logs_boot = await _executar_comandos_maestro(comandos_boot)
            texto_boot = _truncate(texto_boot, limit=8000)
            log_raciocinio.extend(logs_boot)

            mensagens.append({
                "role": "user",
                "content": "SISTEMA (Pré-contexto executado automaticamente):\n" + texto_boot
            })
            mensagens.append({
                "role": "assistant",
                "content": "Contexto recebido. Aguardando comando."
            })
        except Exception as e:
            erro_bootstrap = traceback.format_exc()
            log_raciocinio.append(
                "ERRO NO BOOTSTRAP JSON: as pré-ações automáticas não foram injetadas.\n"
                f"Detalhe: {str(e)}\n"
                f"Rastreio completo:\n{erro_bootstrap}"
            )

    mensagens.append({"role": "user", "content": mensagem})
    resposta_final = ""
    erros_formato_consecutivos = 0

    try:
        for rodada in range(50):
            resposta_ia = await call_llm_messages(cfg, mensagens)

            log_raciocinio.append(f"--- [RODADA {rodada+1}] ---")
            log_raciocinio.append(f"RAW DA IA:\n{resposta_ia}")

            texto_limpo = _limpar_resposta_modelo_para_json(resposta_ia)

            vals, rest = _parse_json_sequence(texto_limpo.strip())

            if rest.strip() or len(vals) != 1:
                erros_formato_consecutivos += 1
                log_raciocinio.append(
                    f"⚠️ ERRO: Resposta fora do padrão ({erros_formato_consecutivos}/"
                    f"{MAX_ERROS_FORMATO_CONSECUTIVOS})."
                )
                if erros_formato_consecutivos >= MAX_ERROS_FORMATO_CONSECUTIVOS:
                    resposta_final = (
                        "A IA respondeu fora do protocolo JSON por várias tentativas seguidas. "
                        "Verifique o Log de Raciocínio e ajuste o prompt/modelo."
                    )
                    log_raciocinio.append("FIM: limite de correções de formato atingido.")
                    break
                mensagens.append({"role": "assistant", "content": resposta_ia})
                mensagens.append({"role": "user", "content": _protocolo_json_reenvio_msg()}) # Gemma ama 'user'
                continue

            erros_formato_consecutivos = 0
            comandos = vals[0]

            if isinstance(comandos, dict):
                if comandos.get("acao") == "responder":
                    resposta_final = comandos.get("resposta", resposta_ia)
                    log_raciocinio.append("FIM: A IA concluiu a investigação.")
                    break
                comandos_lista = [comandos]
            elif isinstance(comandos, list):
                comandos_lista = comandos
            else:
                mensagens.append({"role": "assistant", "content": resposta_ia})
                mensagens.append({"role": "user", "content": _protocolo_json_reenvio_msg()})
                continue

            texto_devolucao, logs_exec = await _executar_comandos_maestro(comandos_lista)
            log_raciocinio.extend(logs_exec)

            mensagens.append({"role": "assistant", "content": resposta_ia})
            mensagens.append({"role": "user", "content": "SISTEMA (Resultado dos endpoints):\n" + texto_devolucao}) # Para não quebrar o Gemma

        if not resposta_final:
            resposta_final = "A IA atingiu o limite de reflexões e não gerou uma resposta final."

    except Exception as e:
        # O RASTREIO DA VERDADE
        erro_trace = traceback.format_exc()
        resposta_final = "Erro crítico. Verifique o Log de Raciocínio."
        log_raciocinio.append(f"ERRO FATAL (Rastreio Completo):\n{erro_trace}")

    log_str = "\n".join(log_raciocinio)
    log_interaction(mensagem if origem == "Chat" else f"[{origem}] {mensagem}", log_str, resposta_final)

    return {"resposta_final": resposta_final, "logs": log_raciocinio}
