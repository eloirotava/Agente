import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY", "").strip()
MAESTRO_API_TOKEN = os.getenv("MAESTRO_API_TOKEN", "").strip()

DEFAULT_LLM_PROVIDER_CODE = '''# Configure TODO o acesso ao modelo dentro desta def.
# Exemplo: importe httpx aqui ou dentro da função, defina URL/modelo/token,
# envie `messages` ao backend e retorne o texto da resposta.
# Para segredos, prefira ler de variáveis de ambiente com os.getenv().

async def gerar_resposta(messages, cfg):
    return '{"acao":"responder","resposta":"Configure o provider LLM em /config."}'
'''

DEFAULTS = {
    "maestro_api_token": MAESTRO_API_TOKEN,
    "llm_provider_code": DEFAULT_LLM_PROVIDER_CODE,
    "scheduler_condition_hard_timeout_seconds": "",
    "scheduler_maestro_hard_timeout_seconds": "",
    "scheduler_max_concurrent_jobs": "1",
    "scheduler_default_hook_slug": ""
}
