import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY", "").strip()
MAESTRO_API_TOKEN = os.getenv("MAESTRO_API_TOKEN", "").strip()

DEFAULTS = {
    "api_provider": "azure",  # ADICIONADO: azure ou openai
    "api_base": "https://apit.petrobras.com.br/ia/openai/v1/openai-azure/openai",
    "deployment_id": "gpt-5-chat-petrobras",
    "api_version": "2025-01-01-preview",
    "api_key": "",
    "ca_cert": "",
    "temperature": "0.2",
    "max_tokens": "",
    "maestro_api_token": MAESTRO_API_TOKEN,
    "llm_provider_mode": "builtin",
    "llm_provider_code": "",
    "scheduler_condition_timeout_seconds": "10",
    "scheduler_maestro_timeout_seconds": "300",
    "scheduler_max_concurrent_jobs": "1"
}
