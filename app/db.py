import json
import sqlite3
from pathlib import Path
from app.settings import DEFAULTS

DB_PATH = Path("app.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    with get_conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS config_kv (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS bot_contexts (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description_for_ai TEXT,
            content TEXT NOT NULL,
            bootstrap_json TEXT DEFAULT ''
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS bot_tools (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description_for_ai TEXT,
            tool_context TEXT,
            content TEXT NOT NULL
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS interactions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            mensagem_usuario TEXT,
            log_raciocinio TEXT,
            resposta_final TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS bot_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            prompt TEXT NOT NULL,
            schedule_hours TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
        """)


        c.execute("""
        CREATE TABLE IF NOT EXISTS endpoint_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            endpoint_kind TEXT NOT NULL,
            slug TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            description_for_ai TEXT DEFAULT '',
            tool_context TEXT DEFAULT '',
            content TEXT DEFAULT '',
            bootstrap_json TEXT DEFAULT '',
            change_note TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            is_deleted_snapshot INTEGER DEFAULT 0,
            UNIQUE(endpoint_kind, slug, version_number)
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS config_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_number INTEGER NOT NULL UNIQUE,
            config_json TEXT NOT NULL,
            change_note TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS bot_hooks (
            slug TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            content TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)

        try: c.execute("ALTER TABLE bot_tasks ADD COLUMN condition_script TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass
        try: c.execute("ALTER TABLE bot_contexts ADD COLUMN bootstrap_json TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass

        cur = c.execute("SELECT COUNT(*) n FROM config_kv")
        if cur.fetchone()["n"] == 0:
            for k, v in DEFAULTS.items():
                c.execute("INSERT INTO config_kv VALUES (?, ?)", (k, v))

        cur = c.execute("SELECT COUNT(*) n FROM bot_contexts WHERE slug='system_prompt'")
        if cur.fetchone()["n"] == 0:
            c.execute(
                "INSERT INTO bot_contexts (slug, title, description_for_ai, content, bootstrap_json) VALUES (?, ?, ?, ?, ?)",
                (
                    "system_prompt",
                    "Diretriz Operacional Base",
                    "",
                    "Você é o Agente Rotava, um assistente industrial rigoroso. Use os endpoints disponíveis para responder com precisão operacional.",
                    ""
                )
            )
        c.commit()

# --- Funções de acesso ---
def get_config():
    cfg = dict(DEFAULTS)
    with get_conn() as c:
        for r in c.execute("SELECT k, v FROM config_kv"):
            cfg[r["k"]] = r["v"]
    return cfg

def save_config(data: dict, change_note: str = ""):
    before = get_config()
    with get_conn() as c:
        for k, v in data.items():
            c.execute("""
            INSERT INTO config_kv (k, v)
            VALUES (?, ?)
            ON CONFLICT(k) DO UPDATE SET v=excluded.v
            """, (k, v))
        c.commit()
    after = get_config()
    comparable_before = {k: v for k, v in before.items() if "key" not in k.lower() and "token" not in k.lower()}
    comparable_after = {k: v for k, v in after.items() if "key" not in k.lower() and "token" not in k.lower()}
    if comparable_before != comparable_after:
        record_config_version(after, change_note or "Configuração salva")

def get_context(slug: str):
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_contexts WHERE slug = ?", (slug,))
        row = cur.fetchone()
        return dict(row) if row else None

def get_general_contexts():
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_contexts WHERE slug != 'system_prompt'")
        return [dict(r) for r in cur.fetchall()]

def save_context(slug: str, title: str, description_for_ai: str, content: str, bootstrap_json: str = "", change_note: str = ""):
    old = get_context(slug)
    with get_conn() as c:
        c.execute("""
        INSERT INTO bot_contexts (slug, title, description_for_ai, content, bootstrap_json)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            title=excluded.title,
            description_for_ai=excluded.description_for_ai,
            content=excluded.content,
            bootstrap_json=excluded.bootstrap_json
        """, (slug, title, description_for_ai, content, bootstrap_json))
        c.commit()
    data = {"title": title, "description_for_ai": description_for_ai, "content": content, "bootstrap_json": bootstrap_json}
    if not old or any((old.get(k) or "") != (data.get(k) or "") for k in data):
        record_endpoint_version("context", slug, data, change_note or "Contexto salvo")

#  NOVA FUNÇÃO
def delete_context(slug: str):
    if slug == "system_prompt":
        return
    with get_conn() as c:
        c.execute("DELETE FROM bot_contexts WHERE slug = ?", (slug,))
        c.commit()

def get_tool(slug: str):
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_tools WHERE slug = ?", (slug,))
        row = cur.fetchone()
        return dict(row) if row else None

def get_all_tools():
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_tools")
        return [dict(r) for r in cur.fetchall()]

def save_tool(slug: str, title: str, description_for_ai: str, tool_context: str, content: str, change_note: str = ""):
    old = get_tool(slug)
    with get_conn() as c:
        c.execute("""
        INSERT INTO bot_tools (slug, title, description_for_ai, tool_context, content)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            title=excluded.title,
            description_for_ai=excluded.description_for_ai,
            tool_context=excluded.tool_context,
            content=excluded.content
        """, (slug, title, description_for_ai, tool_context, content))
        c.commit()
    data = {"title": title, "description_for_ai": description_for_ai, "tool_context": tool_context, "content": content}
    if not old or any((old.get(k) or "") != (data.get(k) or "") for k in data):
        record_endpoint_version("tool", slug, data, change_note or "Endpoint Python salvo")

#  NOVA FUNÇÃO
def delete_tool(slug: str):
    with get_conn() as c:
        c.execute("DELETE FROM bot_tools WHERE slug = ?", (slug,))
        c.commit()

def log_interaction(mensagem: str, log_str: str, resposta: str):
    with get_conn() as c:
        c.execute("""
        INSERT INTO interactions_log (mensagem_usuario, log_raciocinio, resposta_final)
        VALUES (?, ?, ?)
        """, (mensagem, log_str, resposta))
        c.commit()

def get_all_logs():
    with get_conn() as c:
        cur = c.execute("SELECT * FROM interactions_log ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]

def get_all_tasks():
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_tasks ORDER BY id DESC")
        return [dict(r) for r in cur.fetchall()]

def get_task(task_id: int):
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        return dict(row) if row else None

def save_task(title: str, prompt: str, schedule_hours: str, condition_script: str, change_note: str = ""):
    with get_conn() as c:
        c.execute("""
        INSERT INTO bot_tasks (title, prompt, schedule_hours, condition_script)
        VALUES (?, ?, ?, ?)
        """, (title, prompt, schedule_hours, condition_script))
        task_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.commit()
    record_endpoint_version("task", str(task_id), {
        "title": title,
        "description_for_ai": "1",
        "tool_context": schedule_hours,
        "content": prompt,
        "bootstrap_json": condition_script,
    }, change_note or "Rotina criada")

def update_task(task_id: int, title: str, prompt: str, schedule_hours: str, condition_script: str, change_note: str = ""):
    old = get_task(task_id)
    with get_conn() as c:
        c.execute("""
        UPDATE bot_tasks
        SET title = ?, prompt = ?, schedule_hours = ?, condition_script = ?
        WHERE id = ?
        """, (title, prompt, schedule_hours, condition_script, task_id))
        c.commit()
    data = {
        "title": title,
        "description_for_ai": str(old.get("active", 1) if old else 1),
        "tool_context": schedule_hours,
        "content": prompt,
        "bootstrap_json": condition_script,
    }
    if not old or any(str(old.get({"tool_context":"schedule_hours", "content":"prompt", "bootstrap_json":"condition_script", "description_for_ai":"active"}.get(k, k)) or "") != str(data.get(k) or "") for k in data):
        record_endpoint_version("task", str(task_id), data, change_note or "Rotina atualizada")

def delete_task(task_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM bot_tasks WHERE id = ?", (task_id,))
        c.commit()


def get_hook(slug: str):
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_hooks WHERE slug = ?", (slug,))
        row = cur.fetchone()
        return dict(row) if row else None

def get_all_hooks():
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_hooks ORDER BY title COLLATE NOCASE")
        return [dict(r) for r in cur.fetchall()]

def save_hook(slug: str, title: str, description: str, content: str, active: int = 1, change_note: str = ""):
    old = get_hook(slug)
    with get_conn() as c:
        c.execute("""
        INSERT INTO bot_hooks (slug, title, description, content, active, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(slug) DO UPDATE SET
            title=excluded.title,
            description=excluded.description,
            content=excluded.content,
            active=excluded.active,
            updated_at=CURRENT_TIMESTAMP
        """, (slug, title, description, content, active))
        c.commit()
    data = {
        "title": title,
        "description_for_ai": description,
        "tool_context": str(active),
        "content": content,
    }
    hook_key_map = {"description_for_ai": "description", "tool_context": "active"}
    if not old or any(str(old.get(hook_key_map.get(k, k)) or "") != str(data.get(k) or "") for k in data):
        record_endpoint_version("hook", slug, data, change_note or "Hook salvo")

def delete_hook(slug: str):
    with get_conn() as c:
        c.execute("DELETE FROM bot_hooks WHERE slug = ?", (slug,))
        c.commit()


def _next_endpoint_version(c, endpoint_kind: str, slug: str) -> int:
    cur = c.execute(
        "SELECT COALESCE(MAX(version_number), 0) + 1 n FROM endpoint_versions WHERE endpoint_kind=? AND slug=?",
        (endpoint_kind, slug),
    )
    return int(cur.fetchone()["n"])


def record_endpoint_version(endpoint_kind: str, slug: str, data: dict, change_note: str = "") -> int:
    with get_conn() as c:
        version = _next_endpoint_version(c, endpoint_kind, slug)
        c.execute(
            """
            INSERT INTO endpoint_versions (
                endpoint_kind, slug, version_number, title, description_for_ai,
                tool_context, content, bootstrap_json, change_note, is_deleted_snapshot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                endpoint_kind,
                slug,
                version,
                data.get("title") or slug,
                data.get("description_for_ai") or "",
                data.get("tool_context") or "",
                data.get("content") or "",
                data.get("bootstrap_json") or "",
                change_note or "",
                int(bool(data.get("is_deleted_snapshot"))),
            ),
        )
        c.commit()
        return version


def get_endpoint_versions(endpoint_kind: str, slug: str):
    with get_conn() as c:
        cur = c.execute(
            "SELECT * FROM endpoint_versions WHERE endpoint_kind=? AND slug=? ORDER BY version_number DESC",
            (endpoint_kind, slug),
        )
        return [dict(r) for r in cur.fetchall()]


def get_endpoint_version(version_id: int):
    with get_conn() as c:
        cur = c.execute("SELECT * FROM endpoint_versions WHERE id=?", (version_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def delete_endpoint_version(version_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM endpoint_versions WHERE id=?", (version_id,))
        c.commit()


def restore_endpoint_version(version_id: int):
    version = get_endpoint_version(version_id)
    if not version:
        return None

    kind = version["endpoint_kind"]
    slug = version["slug"]

    with get_conn() as c:
        if kind == "context":
            c.execute(
                """
                INSERT INTO bot_contexts (slug, title, description_for_ai, content, bootstrap_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title,
                    description_for_ai=excluded.description_for_ai,
                    content=excluded.content,
                    bootstrap_json=excluded.bootstrap_json
                """,
                (
                    slug,
                    version["title"],
                    version["description_for_ai"],
                    version["content"],
                    version["bootstrap_json"],
                ),
            )
        elif kind == "tool":
            c.execute(
                """
                INSERT INTO bot_tools (slug, title, description_for_ai, tool_context, content)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title,
                    description_for_ai=excluded.description_for_ai,
                    tool_context=excluded.tool_context,
                    content=excluded.content
                """,
                (
                    slug,
                    version["title"],
                    version["description_for_ai"],
                    version["tool_context"],
                    version["content"],
                ),
            )
        elif kind == "hook":
            c.execute(
                """
                INSERT INTO bot_hooks (slug, title, description, content, active, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(slug) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    content=excluded.content,
                    active=excluded.active,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    slug,
                    version["title"],
                    version["description_for_ai"],
                    version["content"],
                    int(version["tool_context"] or 1),
                ),
            )
        elif kind == "task":
            task_id = int(slug)
            c.execute(
                """
                INSERT INTO bot_tasks (id, title, prompt, schedule_hours, active, condition_script)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    prompt=excluded.prompt,
                    schedule_hours=excluded.schedule_hours,
                    active=excluded.active,
                    condition_script=excluded.condition_script
                """,
                (
                    task_id,
                    version["title"],
                    version["content"],
                    version["tool_context"],
                    int(version["description_for_ai"] or 1),
                    version["bootstrap_json"],
                ),
            )
        else:
            return None
        c.commit()

    return version


def _next_config_version(c) -> int:
    cur = c.execute("SELECT COALESCE(MAX(version_number), 0) + 1 n FROM config_versions")
    return int(cur.fetchone()["n"])


def record_config_version(config: dict, change_note: str = "") -> int:
    safe_config = dict(config)
    for key in list(safe_config):
        if "key" in key.lower() or "token" in key.lower():
            safe_config[key] = "********" if safe_config.get(key) else ""
    with get_conn() as c:
        version = _next_config_version(c)
        c.execute(
            "INSERT INTO config_versions (version_number, config_json, change_note) VALUES (?, ?, ?)",
            (version, json.dumps(safe_config, ensure_ascii=False, sort_keys=True), change_note or ""),
        )
        c.commit()
        return version


def get_config_versions():
    with get_conn() as c:
        cur = c.execute("SELECT * FROM config_versions ORDER BY version_number DESC")
        rows = []
        for r in cur.fetchall():
            item = dict(r)
            item["config"] = json.loads(item["config_json"])
            rows.append(item)
        return rows


def delete_config_version(version_id: int):
    with get_conn() as c:
        c.execute("DELETE FROM config_versions WHERE id=?", (version_id,))
        c.commit()


def get_latest_endpoint_version_number(endpoint_kind: str, slug: str) -> int | None:
    with get_conn() as c:
        cur = c.execute(
            "SELECT MAX(version_number) n FROM endpoint_versions WHERE endpoint_kind=? AND slug=?",
            (endpoint_kind, slug),
        )
        value = cur.fetchone()["n"]
        return int(value) if value is not None else None
