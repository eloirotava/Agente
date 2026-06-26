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

def save_config(data: dict):
    with get_conn() as c:
        for k, v in data.items():
            c.execute("""
            INSERT INTO config_kv (k, v)
            VALUES (?, ?)
            ON CONFLICT(k) DO UPDATE SET v=excluded.v
            """, (k, v))
        c.commit()

def get_context(slug: str):
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_contexts WHERE slug = ?", (slug,))
        row = cur.fetchone()
        return dict(row) if row else None

def get_general_contexts():
    with get_conn() as c:
        cur = c.execute("SELECT * FROM bot_contexts WHERE slug != 'system_prompt'")
        return [dict(r) for r in cur.fetchall()]

def save_context(slug: str, title: str, description_for_ai: str, content: str, bootstrap_json: str = ""):
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

def save_tool(slug: str, title: str, description_for_ai: str, tool_context: str, content: str):
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

def save_task(title: str, prompt: str, schedule_hours: str, condition_script: str):
    with get_conn() as c:
        c.execute("""
        INSERT INTO bot_tasks (title, prompt, schedule_hours, condition_script)
        VALUES (?, ?, ?, ?)
        """, (title, prompt, schedule_hours, condition_script))
        c.commit()

def update_task(task_id: int, title: str, prompt: str, schedule_hours: str, condition_script: str):
    with get_conn() as c:
        c.execute("""
        UPDATE bot_tasks
        SET title = ?, prompt = ?, schedule_hours = ?, condition_script = ?
        WHERE id = ?
        """, (title, prompt, schedule_hours, condition_script, task_id))
        c.commit()

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

def save_hook(slug: str, title: str, description: str, content: str, active: int = 1):
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

def delete_hook(slug: str):
    with get_conn() as c:
        c.execute("DELETE FROM bot_hooks WHERE slug = ?", (slug,))
        c.commit()
