# Agente Rotava

Agente Rotava é um assistente industrial local com interface web, memória técnica, endpoints Python opcionais e rotinas agendadas. A proposta é centralizar perguntas, manuais, automações e chamadas a modelos de linguagem em um único serviço FastAPI, rodando em ambiente local/VPN.

## Objetivo

O Agente Rotava foi pensado para apoiar operação e engenharia em tarefas como:

- responder dúvidas usando uma Diretriz Operacional Base;
- consultar manuais e contextos técnicos cadastrados;
- cadastrar endpoints manuais ou Python previamente auditados;
- registrar logs de raciocínio e respostas;
- disparar rotinas periódicas com gatilhos opcionais em Python;
- integrar com Azure OpenAI corporativo, OpenAI compatível ou endpoints locais compatíveis com `/chat/completions`.

## Arquitetura em alto nível

```text
Usuário / Rotina
      |
      v
FastAPI + Jinja UI
      |
      v
Maestro (/api/maestro)
      |
      +--> SQLite: configurações, endpoints, logs e tarefas
      |
      +--> Cliente APIM/OpenAI compatível
      |
      +--> Endpoints manuais ou Python auditados
```

Componentes principais:

- `app/main.py`: inicializa o FastAPI, registra rotas e inicia o agendador.
- `app/routers/maestro.py`: orquestra o ciclo modelo -> JSON -> endpoint -> resposta final.
- `app/worker.py`: avalia rotinas periódicas e chama o Maestro.
- `app/db.py`: cria e acessa o SQLite local (`app.db`).
- `app/templates/`: páginas administrativas e de operação.
- `agente_rotava.py`: atalho para iniciar o servidor local.

## Pré-requisitos

- Python 3.10+ recomendado.
- Acesso ao endpoint de modelo configurado, quando for usar chat real.
- VPN/rede local liberada para o endpoint corporativo, se aplicável.

Instale as dependências:

```bash
pip install fastapi uvicorn python-multipart httpx jinja2 python-dotenv
```

Opcionalmente, crie um ambiente virtual antes:

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install fastapi uvicorn python-multipart httpx jinja2 python-dotenv
```

### Linux/macOS

```bash
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn python-multipart httpx jinja2 python-dotenv
```

## Configuração

Informe o token/chave na tela **Configurações**. Se preferir manter a chave fora do banco local, ainda é possível criar um arquivo `.env` na raiz do projeto:

```env
API_KEY=sua_chave_ou_token_aqui
```

As demais opções podem ser ajustadas pela tela **Configurações**:

- provedor (`azure`, `openai`/compatível ou `gemini` via compatibilidade OpenAI);
- URL base; para Gemini, use `https://generativelanguage.googleapis.com/v1beta/openai` ou informe o endpoint completo terminado em `/chat/completions`;
- token/API key, que tem prioridade sobre o `API_KEY` do `.env`;
- modelo principal;
- versão da API;
- certificado corporativo; deve ser caminho de arquivo CA bundle, não token/API key; deixe em branco para usar o padrão do sistema;
- temperatura;
- limite de tokens.

> Observação: a solução foi desenhada para execução local/VPN. HTTP local é suficiente para esse cenário, desde que a máquina e a VPN estejam sob controle operacional.

## Como executar

Pela forma direta:

```bash
uvicorn app.main:app --reload
```

Ou pelo atalho:

```bash
python agente_rotava.py
```

Depois acesse:

```text
http://127.0.0.1:8000
```

### Google Gemini / Gemma

Para usar a API Gemini com modelos Google, selecione **Google Gemini API (OpenAI compatível)**, preencha **Token / API key** na própria tela, use a URL base `https://generativelanguage.googleapis.com/v1beta/openai` e informe o modelo no campo **Modelo principal**.

Se você estiver usando um servidor local ou endpoint de terceiros servindo Gemma em formato OpenAI, mantenha o provedor **OpenAI compatível / Endpoint local** e aponte a URL base para o prefixo do serviço. O cliente também aceita que a URL já venha completa com `/chat/completions`, evitando duplicar esse trecho.

## Fluxo do Maestro

O Maestro trabalha com um protocolo JSON:

1. O usuário envia uma pergunta pelo chat ou uma rotina dispara um prompt.
2. O Maestro monta o system prompt com a Diretriz Operacional Base e os resumos dos recursos disponíveis.
3. O modelo deve responder com exatamente um JSON:
   - uma ação única;
   - uma lista de ações;
   - ou uma resposta final.
4. O Maestro consulta endpoints manuais ou executa endpoints Python solicitados.
5. O resultado dos endpoints volta ao modelo.
6. O ciclo continua até o modelo responder com:

```json
{"acao": "responder", "resposta": "texto final para o usuário"}
```

Exemplo de chamada de manual/contexto:

```json
{"acao": "ler_contexto", "slug": "tags_pi"}
```

Exemplo de lote:

```json
[
  {"acao": "ler_contexto", "slug": "tags_pi"},
  {"acao": "consultar_pi", "tag": "TAG_EXEMPLO"}
]
```

## Endpoints

A tela **Endpoints** concentra o contexto inicial, os manuais e os recursos Python em uma única área.

### Contexto inicial

O endpoint protegido **Diretriz Operacional Base** continua sendo o prompt base do Agente Rotava. Ele não é removível e permite cadastrar um `bootstrap_json`, que é uma lista JSON de pré-ações executadas antes da primeira chamada ao modelo.

Exemplo:

```json
[
  {"acao": "ler_contexto", "slug": "tags_pi"}
]
```

Se o bootstrap falhar, o erro é registrado no log de raciocínio da interação para facilitar auditoria e ajuste.

### Endpoints manuais

Quando o campo de código Python fica vazio, o endpoint é salvo como manual/contexto consultável. Se o resumo para o Maestro estiver preenchido, apenas essa descrição é injetada no prompt inicial; se ficar em branco, o endpoint continua cadastrado, mas não é anunciado automaticamente. O conteúdo completo só é lido quando o modelo pede explicitamente.

### Endpoints Python opcionais

Quando o campo de código Python é preenchido, o endpoint mantém o comportamento executável atual. Para ser executável pelo Maestro, o código deve expor uma função:

```python
def executar(cmd: dict):
    # cmd contém o JSON enviado pelo modelo
    return "resultado textual para devolver ao Maestro"
```

Exemplo simples:

```python
def executar(cmd: dict):
    nome = cmd.get("nome", "operador")
    return f"Olá, {nome}. Endpoint executado com sucesso."
```

> Importante: apesar da solução rodar localmente/VPN e os scripts serem auditados antes de entrar em operação, endpoints Python têm alto privilégio no processo. Mantenha revisão manual, histórico e acesso restrito aos cadastros.

## Rotinas agendadas

A tela **Rotinas** permite cadastrar automações periódicas.

Formatos aceitos:

- horário fixo: `08:00`;
- múltiplos horários: `08:00, 16:00`;
- intervalo em minutos: `*/5m`.

Cada rotina pode ter um script opcional com:

```python
def avaliar():
    return False
```

Comportamento esperado:

- `False`, `None`, string vazia ou valor falso: não dispara;
- string: dispara e adiciona a string como alerta/contexto;
- outro valor verdadeiro: dispara com o prompt original.

## Logs e auditoria

A tela **Logs** registra:

- origem da chamada;
- mensagem do usuário ou rotina;
- system prompt injetado;
- respostas brutas do modelo;
- endpoints acionados;
- resposta final;
- erros críticos e falhas de bootstrap.

Use esses logs para auditar comportamento do modelo, ajustar prompts e validar endpoints antes de operação.

## Banco de dados

O Agente Rotava usa SQLite local em `app.db`. As tabelas principais são criadas automaticamente no startup:

- `config_kv`;
- `bot_contexts`;
- `bot_tools`;
- `interactions_log`;
- `bot_tasks`.

Para exportar conhecimento cadastrado em relatório Markdown:

```bash
python exportar_banco.py
```

## Configuração versionável em arquivos

Além do SQLite operacional, o Agente Rotava pode exportar a configuração editável para uma pasta versionável (`agente_rotava_config/`). A ideia é separar:

- **arquivos versionáveis**: Diretriz Operacional Base, `bootstrap_json`, endpoints manuais, endpoints Python, contratos de uso e rotinas;
- **SQLite operacional**: logs, auditoria, heartbeat, métricas e estado gerado durante a execução.

Exportar a configuração atual:

```bash
python exportar_config.py --out agente_rotava_config --clean
```

Importar de volta para o SQLite local:

```bash
python importar_config.py agente_rotava_config
```

Estrutura esperada:

```text
agente_rotava_config/
  manifest.json
  base/
    system_prompt.md
    bootstrap.json
    manifest.json
  knowledge/
    exemplo.json
    exemplo.md
  tools/
    consultar_pi/
      manifest.json
      tool_context.md
      tool.py
  tasks/
    rotina_exemplo.json
  settings/
    config_public.json
```

O exportador não inclui segredos de ambiente como `API_KEY`; eles continuam no `.env` ou na configuração local da máquina.

## Segurança operacional assumida

Esta primeira versão assume:

- execução local/VPN;
- acesso restrito à máquina e às telas administrativas;
- auditoria manual dos scripts Python opcionais antes da operação;
- uso de HTTP local suficiente para o ambiente proposto;
- segredos reais fora do repositório, preferencialmente em `.env` ou configuração local não versionada.

Recomendações práticas:

- não versionar arquivos com chaves, tokens ou configurações sensíveis;
- revisar qualquer endpoint Python antes de habilitar;
- limitar quem pode editar endpoints e rotinas;
- fazer backup periódico do `app.db`;
- acompanhar os logs de raciocínio após alterações de prompt/endpoints.

## Desenvolvimento rápido

Verificar sintaxe Python:

```bash
python -m compileall -q .
```

Ver estado do Git:

```bash
git status --short
```

## Hooks HTTP genéricos

A tela **Hooks** permite cadastrar entradas HTTP genéricas para eventos externos em tempo real. Cada hook recebe JSON em:

```text
POST /hook/{slug}
```

O `slug` identifica o cadastro. O corpo precisa ser um objeto JSON. O script Python do hook deve expor uma função `receber(payload, headers)` ou `receber(payload)`. Esse script trata o JSON recebido, valida tokens quando necessário e retorna a mensagem que será enviada ao Maestro em background. A resposta HTTP ao chamador é rápida e confirma apenas o recebimento.

Exemplo mínimo:

```python
def receber(payload: dict, headers: dict):
    texto = payload.get("texto", payload)
    return {
        "origem": "HOOK: exemplo",
        "mensagem": f"Evento externo recebido: {texto}",
        "contexto": f"Payload bruto: {payload}",
    }
```

Retornos aceitos:

- `str`: vira diretamente a mensagem do Maestro;
- `dict`: pode informar `mensagem`, `origem` e `contexto`;
- `None`: envia o JSON bruto como mensagem.

Exemplo de chamada local:

```bash
curl -s -X POST http://127.0.0.1:8000/hook/exemplo \
  -H 'Content-Type: application/json' \
  -d '{"texto":"ping local","origem":"curl"}'
```

A resposta HTTP confirma rapidamente o recebimento do evento. O processamento pelo Maestro segue em background e fica registrado nos logs. Para respostas ao canal de origem, cadastre endpoints Python já conhecidos pelo Maestro; o payload de entrada pode carregar IDs de chat, canal ou mensagem para que a LLM acione o endpoint correto.

## API local do Maestro (OpenAI compatível)

O endpoint protegido `POST /api/maestro` aceita chamadas no formato OpenAI Chat Completions. Ele é uma porta de entrada para clientes internos/autorizados usarem o Maestro com a Diretriz Operacional Base, contextos e endpoints Python já cadastrados.

Configure o **Token local do Maestro** na tela **Configurações** ou defina `MAESTRO_API_TOKEN` no `.env`. Esse token é separado do token/API key usado para chamar o modelo upstream.

Exemplo:

```bash
curl -s -X POST http://127.0.0.1:8000/api/maestro \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer seu-token-local' \
  -d '{
    "model": "botmig-maestro",
    "messages": [
      {"role": "user", "content": "mande pong no telegram"}
    ]
  }'
```

Resposta resumida:

```json
{
  "object": "chat.completion",
  "model": "botmig-maestro",
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "resposta final do Maestro"
      },
      "finish_reason": "stop"
    }
  ]
}
```

Por segurança, `/api/maestro` não aceita chamadas sem token. A página **Assistente** continua chamando o Maestro diretamente no Python. A agenda usa esse endpoint local com o token configurado.
