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

DEFAULT_HTTP_ROUTES_CODE = r'''async def rotear(request, path, cfg, helpers):
    import json
    from app.db import get_all_logs, get_conn

    HTMLResponse = helpers["HTMLResponse"]
    RedirectResponse = helpers["RedirectResponse"]
    templates = helpers["templates"]

    def render_assistant_html(html, **values):
        rendered = html or ""
        for key, value in values.items():
            rendered = rendered.replace("{{ " + key + " }}", str(value))
            rendered = rendered.replace("{{" + key + "}}", str(value))
        return rendered

    if path == "chat" and request.method == "GET":
        html = (cfg.get("assistant_html_code") or "").strip()
        if html:
            return HTMLResponse(render_assistant_html(
                html, answer="", error="", logs_json="[]", assistant_payload_json="{}"
            ))
        return templates.TemplateResponse(request=request, name="chat.html", context={})

    if path == "chat" and request.method == "POST":
        code = (cfg.get("assistant_handler_code") or "").strip()
        if code:
            scope = {"json": json}
            async def processar_orquestracao(*args, **kwargs):
                return await helpers["processar_orquestracao"](*args, **kwargs)
            html = cfg.get("assistant_html_code") or ""
            scope.update({
                "processar_orquestracao": processar_orquestracao,
                "render_html": lambda **values: HTMLResponse(render_assistant_html(html, **values)),
                "json": json,
            })
            exec(code, scope, scope)
            fn = scope.get("atender") or scope.get("executar") or scope.get("handle")
            if not callable(fn):
                return HTMLResponse("assistant_handler_code sem atender(...)", status_code=500)
            result = fn(request, cfg, {
                "processar_orquestracao": processar_orquestracao,
                "render_html": lambda **values: HTMLResponse(render_assistant_html(html, **values)),
                "json": json,
            })
            if hasattr(result, "__await__"):
                result = await result
            return result

        form = await request.form()
        message = form.get("message") or ""
        resultado = await helpers["processar_orquestracao"](mensagem=message, origem="Chat")
        return templates.TemplateResponse(request=request, name="chat.html", context={
            "message": message, "answer": resultado["resposta_final"], "logs": resultado["logs"]
        })

    if path == "logs" and request.method == "GET":
        return templates.TemplateResponse(request=request, name="logs.html", context={
            "logs": get_all_logs(),
            "cleared": request.query_params.get("cleared"),
        })

    if path == "logs/clear" and request.method == "POST":
        with get_conn() as c:
            c.execute("DELETE FROM interactions_log")
            c.commit()
        return RedirectResponse(url="/logs?cleared=1", status_code=303)

    if path == "agenda" and request.method == "GET":
        from app.db import get_all_tasks, get_task, get_endpoint_versions
        edit_id = request.query_params.get("edit_task")
        edit = get_task(int(edit_id)) if edit_id and edit_id.isdigit() else None
        tasks = get_all_tasks()
        rows = ""
        for t in tasks:
            rows += f"""<div class='record-card'><h3>{t['title']}</h3><p><strong>Quando:</strong> {t['schedule_hours']}</p><p>{t['prompt']}</p><div class='btn-row'><a class='btn secondary-btn' href='/agenda?edit_task={t['id']}'>Editar</a><form method='post' action='/agenda/delete/{t['id']}'><button class='danger-btn'>Remover</button></form></div></div>"""
        versions = get_endpoint_versions("task", str(edit["id"])) if edit else []
        version_rows = ""
        for v in versions:
            version_rows += f"<details class='record-card'><summary>v{v['version_number']} · {v['created_at']} · {v.get('change_note') or 'sem nota'}</summary><pre>{v.get('content') or ''}</pre></details>"
        historico = f"<section class='card'><h2>Histórico da rotina</h2>{version_rows}</section>" if edit else ""
        html = f"""<!doctype html><html lang='pt-br'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Agenda</title><style>
body{{font-family:system-ui;margin:0;background:#020617;color:#e5e7eb;padding:24px;}}a{{color:#38bdf8}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.card{{border:1px solid #334155;border-radius:16px;background:#0f172a;padding:16px;margin-bottom:16px}}label{{display:block;font-weight:700;margin-top:10px}}input,textarea{{width:100%;box-sizing:border-box;border-radius:10px;border:1px solid #334155;background:#020617;color:#e5e7eb;padding:10px}}button,.btn{{display:inline-block;border:0;border-radius:999px;background:#38bdf8;color:#082f49;padding:10px 14px;font-weight:800;text-decoration:none;cursor:pointer}}.danger-btn{{background:#f87171;color:#450a0a}}.btn-row{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}@media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}</style></head><body>
<div class='card'><h1>Agenda</h1><p>Rotinas salvas no banco e executadas pelo worker. Use <code>*/1m</code>, <code>*/5m</code> ou horários como <code>08:00, 16:00</code>.</p><p><a href='/config#runtime'>Configurar worker/dispatch</a> · <a href='/config#rotas-http'>Configurar rotas</a></p></div>
<div class='grid'><form method='post' action='/agenda' class='card'>
<h2>{'Editar rotina' if edit else 'Nova rotina'}</h2><input type='hidden' name='task_id' value='{edit['id'] if edit else ''}'>
<label>Nota da versão</label><input name='change_note'>
<label>Nome</label><input name='title' required value='{edit['title'] if edit else ''}'>
<label>Quando rodar</label><input name='schedule_hours' required value='{edit['schedule_hours'] if edit else ''}' placeholder='*/1m'>
<label>Gatilho Python opcional</label><textarea name='condition_script' rows='6'>{edit['condition_script'] if edit else ''}</textarea>
<label>Prompt</label><textarea name='prompt' rows='6' required>{edit['prompt'] if edit else ''}</textarea>
<div class='btn-row'><button>Salvar rotina</button><a class='btn' href='/agenda'>Nova/Cancelar</a></div></form>
<section class='card'><h2>Rotinas cadastradas ({len(tasks)})</h2>{rows}</section></div>{historico}</body></html>"""
        return HTMLResponse(html)

    if path == "agenda" and request.method == "POST":
        from app.db import save_task, update_task
        form = await request.form()
        task_id = str(form.get("task_id") or "")
        if task_id.isdigit():
            update_task(int(task_id), form.get("title") or "", form.get("prompt") or "", form.get("schedule_hours") or "", form.get("condition_script") or "", change_note=form.get("change_note") or "")
        else:
            save_task(form.get("title") or "", form.get("prompt") or "", form.get("schedule_hours") or "", form.get("condition_script") or "", change_note=form.get("change_note") or "")
        return RedirectResponse(url="/agenda", status_code=303)

    if path.startswith("agenda/delete/") and request.method == "POST":
        from app.db import delete_task
        task_id = path.rsplit("/", 1)[-1]
        if task_id.isdigit():
            delete_task(int(task_id))
        return RedirectResponse(url="/agenda", status_code=303)

    if path.startswith("hook/") and request.method == "POST":
        slug = path.split("/", 1)[1]
        payload = await request.json()
        result = await helpers["dispatch_hook"](slug, payload, dict(request.headers))
        return {"ok": True, "hook": slug, "result": result}

    return HTMLResponse(f"Rota não configurada: /{path}", status_code=404)
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
    "log_persist_code": DEFAULT_LOG_PERSIST_CODE,
    "http_routes_code": DEFAULT_HTTP_ROUTES_CODE
}
