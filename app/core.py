import json
import asyncio
import inspect
import traceback  # Rastreio completo de erros
from typing import Any, List, Tuple


from app.db import (
    get_config,
    get_context,
    get_general_contexts,
    get_tool,
    get_all_tools,
    log_interaction,
)
from app.llm_gateway import call_llm_messages, config_fingerprint


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


def _normalizar_retorno_core_customizado(resultado: Any) -> tuple[str, List[str]]:
    if isinstance(resultado, dict):
        resposta = str(resultado.get("resposta_final") or resultado.get("resposta") or "")
        logs = resultado.get("logs") or resultado.get("log") or []
        if isinstance(logs, str):
            logs = [logs]
        return resposta, [str(item) for item in logs]

    return str(resultado or ""), ["Core customizado retornou texto simples."]


async def _processar_core_customizado(
    core_code: str,
    mensagem: str,
    origem: str,
    cfg: dict,
) -> dict:
    helpers = {
        "call_llm_messages": call_llm_messages,
        "config_fingerprint": config_fingerprint,
        "get_config": get_config,
        "get_context": get_context,
        "get_general_contexts": get_general_contexts,
        "get_tool": get_tool,
        "get_all_tools": get_all_tools,
        "log_interaction": log_interaction,
        "executar_comandos": _executar_comandos_maestro,
        "limpar_json": _limpar_resposta_modelo_para_json,
        "parse_json_sequence": _parse_json_sequence,
        "truncate": _truncate,
    }
    scope = {"asyncio": asyncio, "json": json, **helpers}
    logs: List[str] = [
        f"[ORIGEM: {origem}]",
        "MAESTRO CORE: executando def customizada de configuração.",
    ]

    try:
        exec(core_code, scope, scope)
        func = (
            scope.get("processar")
            or scope.get("processar_orquestracao")
            or scope.get("executar")
        )
        if not callable(func):
            raise RuntimeError(
                "Core configurado sem função de entrada. Use processar(mensagem, origem, cfg, helpers), "
                "processar_orquestracao(mensagem, origem) ou executar(...)."
            )

        assinatura = inspect.signature(func)
        total_parametros = len(assinatura.parameters)
        if total_parametros <= 2:
            resultado = func(mensagem, origem)
        elif total_parametros == 3:
            resultado = func(mensagem, origem, cfg)
        else:
            resultado = func(mensagem, origem, cfg, helpers)
        if inspect.isawaitable(resultado):
            resultado = await resultado

        resposta_final, logs_customizados = _normalizar_retorno_core_customizado(resultado)
        logs.extend(logs_customizados)
        if not resposta_final:
            resposta_final = "Core customizado executado sem resposta final."
            logs.append("AVISO: core customizado não retornou resposta_final.")
    except Exception:
        resposta_final = "Erro no core customizado do Maestro. Verifique o Log de Raciocínio."
        logs.append(f"ERRO NO CORE CUSTOMIZADO:\n{traceback.format_exc()}")

    log_interaction(
        mensagem if origem == "Chat" else f"[{origem}] {mensagem}",
        "\n".join(logs),
        resposta_final,
    )
    return {"resposta_final": resposta_final, "logs": logs}

async def processar_orquestracao(mensagem: str, origem: str):
    cfg = get_config()
    core_code = (cfg.get("maestro_core_code") or "").strip()
    if core_code:
        return await _processar_core_customizado(core_code, mensagem, origem, cfg)

    resposta_final = "Maestro core não configurado. Cole a def do Maestro em Configurações."
    logs = [
        f"[ORIGEM: {origem}]",
        "MAESTRO CORE: nenhuma def configurada; core padrão desativado.",
    ]
    log_interaction(
        mensagem if origem == "Chat" else f"[{origem}] {mensagem}",
        "\n".join(logs),
        resposta_final,
    )
    return {"resposta_final": resposta_final, "logs": logs}
