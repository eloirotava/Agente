import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("API_KEY", "").strip()
DEFAULT_LLM_PROVIDER_CODE = '''# Configure TODO o acesso ao modelo dentro desta def.
# Exemplo: importe httpx aqui ou dentro da função, defina URL/modelo/token,
# envie `messages` ao backend e retorne o texto da resposta.
# Para segredos, prefira ler de variáveis de ambiente com os.getenv().

async def gerar_resposta(messages, cfg):
    return '{"acao":"responder","resposta":"Configure o provider LLM em /config."}'
'''

DEFAULT_ASSISTANT_HTML_CODE = r'''<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Assistente multimodal</title>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      grid-template-columns: 290px 1fr;
      background: #020617;
      color: #e5e7eb;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    aside {
      border-right: 1px solid rgba(148, 163, 184, .22);
      padding: 18px;
      background: rgba(15, 23, 42, .9);
      overflow-y: auto;
    }
    main {
      min-width: 0;
      display: grid;
      grid-template-rows: auto 1fr auto;
      height: 100vh;
    }
    header, form {
      padding: 18px 22px;
      border-bottom: 1px solid rgba(148, 163, 184, .18);
      background: rgba(15, 23, 42, .72);
    }
    form { border-top: 1px solid rgba(148, 163, 184, .18); border-bottom: 0; }
    h1, h2, p { margin-top: 0; }
    button, .conv-btn {
      border: 0;
      border-radius: 12px;
      padding: 10px 12px;
      font-weight: 800;
      cursor: pointer;
      background: #38bdf8;
      color: #082f49;
    }
    .danger { background: #f87171; color: #450a0a; }
    .ghost { background: rgba(148, 163, 184, .14); color: #e5e7eb; }
    .conv-btn {
      width: 100%;
      margin: 6px 0;
      text-align: left;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .conv-btn.active { outline: 2px solid #38bdf8; }
    #messages {
      overflow-y: auto;
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .msg {
      max-width: 880px;
      padding: 14px 16px;
      border-radius: 16px;
      white-space: pre-wrap;
      line-height: 1.5;
      border: 1px solid rgba(148, 163, 184, .18);
    }
    .user { align-self: flex-end; background: rgba(56, 189, 248, .16); }
    .assistant { align-self: flex-start; background: rgba(30, 41, 59, .82); }
    .meta { color: #94a3b8; font-size: .86rem; margin-bottom: 6px; }
    textarea, input[type=file] {
      width: 100%;
      border-radius: 14px;
      border: 1px solid rgba(148, 163, 184, .3);
      background: #020617;
      color: #e5e7eb;
      padding: 12px;
    }
    textarea { min-height: 92px; resize: vertical; }
    .row { display: grid; grid-template-columns: 1fr auto; gap: 10px; align-items: end; }
    .tools { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
    .hint, .error { color: #94a3b8; font-size: .92rem; }
    .error { color: #fecaca; white-space: pre-wrap; }
    @media (max-width: 820px) { body { grid-template-columns: 1fr; } aside { max-height: 220px; } main { height: auto; min-height: 80vh; } }
  </style>
</head>
<body>
  <aside>
    <h2>Conversas</h2>
    <div class="tools">
      <button type="button" onclick="newConversation()">Nova</button>
      <button type="button" class="danger" onclick="deleteConversation()">Apagar</button>
    </div>
    <div id="conversationList"></div>
  </aside>

  <main>
    <header>
      <h1>Assistente multimodal</h1>
      <p class="hint">Histórico fica no navegador e é reenviado junto com cada mensagem. Aceita texto + imagem.</p>
      <div id="error" class="error">{{ error }}</div>
    </header>

    <section id="messages"></section>

    <form method="post" enctype="multipart/form-data" onsubmit="beforeSubmit()">
      <input type="hidden" name="conversation_id" id="conversation_id">
      <input type="hidden" name="history_json" id="history_json">
      <div class="row">
        <div>
          <textarea id="texto" name="texto" placeholder="Escreva sua mensagem. Ex: descreva a imagem e compare com o histórico."></textarea>
          <input id="imagem" name="imagem" type="file" accept="image/*">
        </div>
        <button type="submit">Enviar tudo</button>
      </div>
    </form>
  </main>

  <script id="assistantPayload" type="application/json">{{ assistant_payload_json }}</script>
  <script>
    const STORAGE_KEY = "agente_assistant_conversations_v1";
    let conversations = loadConversations();
    let activeId = localStorage.getItem("agente_assistant_active") || Object.keys(conversations)[0];

    if (!activeId) newConversation(false);
    applyServerPayload();
    renderAll();

    function loadConversations() {
      try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); }
      catch { return {}; }
    }
    function saveConversations() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
        localStorage.setItem("agente_assistant_active", activeId || "");
      } catch (err) {
        // Proteção contra quota do localStorage. Não persista base64 de imagem aqui.
        for (const conv of Object.values(conversations)) {
          for (const msg of (conv.messages || [])) {
            delete msg.image_preview;
          }
        }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
        localStorage.setItem("agente_assistant_active", activeId || "");
      }
    }
    function newConversation(render = true) {
      activeId = "conv_" + Date.now();
      conversations[activeId] = { title: "Nova conversa", messages: [] };
      saveConversations();
      if (render) renderAll();
    }
    function deleteConversation() {
      if (!activeId) return;
      delete conversations[activeId];
      activeId = Object.keys(conversations)[0];
      if (!activeId) newConversation(false);
      saveConversations();
      renderAll();
    }
    function setActive(id) { activeId = id; saveConversations(); renderAll(); }
    function current() { return conversations[activeId] || { title: "Nova conversa", messages: [] }; }

    function beforeSubmit() {
      const conv = current();
      document.getElementById("conversation_id").value = activeId;
      document.getElementById("history_json").value = JSON.stringify(conv.messages || []);
    }

    function applyServerPayload() {
      let payload = {};
      try { payload = JSON.parse(document.getElementById("assistantPayload").textContent || "{}"); }
      catch { payload = {}; }
      if (!payload || !payload.answer) return;
      activeId = payload.conversation_id || activeId || ("conv_" + Date.now());
      if (!conversations[activeId]) conversations[activeId] = { title: "Nova conversa", messages: [] };
      const conv = conversations[activeId];
      if (payload.user_text || payload.had_image) {
        conv.messages.push({ role: "user", text: payload.user_text || "[imagem]", had_image: !!payload.had_image });
      }
      conv.messages.push({ role: "assistant", text: payload.answer });
      conv.title = (payload.user_text || conv.title || "Conversa").slice(0, 42);
      saveConversations();
      history.replaceState(null, "", location.pathname);
    }

    function renderAll() { renderList(); renderMessages(); }
    function renderList() {
      const el = document.getElementById("conversationList");
      el.innerHTML = "";
      Object.entries(conversations).reverse().forEach(([id, conv]) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "conv-btn ghost" + (id === activeId ? " active" : "");
        btn.textContent = conv.title || "Conversa";
        btn.onclick = () => setActive(id);
        el.appendChild(btn);
      });
    }
    function renderMessages() {
      const el = document.getElementById("messages");
      el.innerHTML = "";
      for (const msg of (current().messages || [])) {
        const div = document.createElement("div");
        div.className = "msg " + (msg.role === "user" ? "user" : "assistant");
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = msg.role === "user" ? (msg.had_image ? "Você · com imagem" : "Você") : "Assistente";
        const body = document.createElement("div");
        body.textContent = msg.text || "";
        div.appendChild(meta);
        div.appendChild(body);
        el.appendChild(div);
      }
      el.scrollTop = el.scrollHeight;
    }
  </script>
</body>
</html>'''

DEFAULT_ASSISTANT_HANDLER_CODE = r'''async def atender(request, cfg, helpers):
    import base64
    import json

    form = await request.form()
    texto = (form.get("texto") or "").strip()
    conversation_id = (form.get("conversation_id") or "").strip()

    try:
        historico = json.loads(form.get("history_json") or "[]")
    except Exception:
        historico = []

    arquivo = form.get("imagem")
    content = []

    if historico:
        linhas = []
        for item in historico[-20:]:
            papel = item.get("role", "user")
            texto_item = item.get("text", "")
            if item.get("had_image"):
                texto_item += " [mensagem anterior tinha imagem]"
            linhas.append(f"{papel}: {texto_item}")
        content.append({
            "type": "text",
            "text": "Histórico recente da conversa:\n" + "\n".join(linhas)
        })

    if texto:
        content.append({"type": "text", "text": texto})

    had_image = bool(arquivo and getattr(arquivo, "filename", ""))
    if had_image:
        raw = await arquivo.read()
        content_type = getattr(arquivo, "content_type", None) or "image/png"
        imagem_b64 = base64.b64encode(raw).decode("ascii")
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{content_type};base64,{imagem_b64}"}
        })

    if not content:
        return helpers["render_html"](
            answer="",
            error="Envie texto, imagem, ou os dois.",
            assistant_payload_json="{}"
        )

    mensagem_para_maestro = content
    resultado = await helpers["processar_orquestracao"](
        mensagem=mensagem_para_maestro,
        origem="Chat multimodal"
    )

    answer = resultado.get("resposta_final", "")
    payload = {
        "conversation_id": conversation_id,
        "user_text": texto,
        "had_image": had_image,
        "answer": answer,
    }
    return helpers["render_html"](
        answer=answer,
        error="",
        assistant_payload_json=json.dumps(payload, ensure_ascii=False)
    )
'''

DEFAULT_LOG_PERSIST_CODE = r'''async def salvar_log(mensagem, log_raciocinio, resposta_final, cfg, helpers):
    import json
    import re

    def limpar(obj):
        texto = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)

        # Troca data URLs/base64 de imagens por marcador curto.
        texto = re.sub(
            r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+",
            "[imagem omitida do log]",
            texto,
        )

        # Cobre também dicts OpenAI-compatible quando viram string.
        texto = re.sub(
            r"'url':\s*'data:image/[^']+'",
            "'url': '[imagem omitida do log]'",
            texto,
        )
        texto = re.sub(
            r'"url":\s*"data:image/[^"]+"',
            '"url": "[imagem omitida do log]"',
            texto,
        )
        return texto

    helpers["default_log_interaction"](
        limpar(mensagem),
        limpar(log_raciocinio),
        limpar(resposta_final),
    )
'''

DEFAULTS = {
    "llm_provider_code": DEFAULT_LLM_PROVIDER_CODE,
    "assistant_html_code": DEFAULT_ASSISTANT_HTML_CODE,
    "assistant_handler_code": DEFAULT_ASSISTANT_HANDLER_CODE,
    "scheduler_condition_hard_timeout_seconds": "",
    "scheduler_maestro_hard_timeout_seconds": "",
    "scheduler_max_concurrent_jobs": "1",
    "scheduler_default_hook_slug": "",
    "scheduler_dispatch_code": "",
    "maestro_core_code": "",
    "log_persist_code": DEFAULT_LOG_PERSIST_CODE
}
