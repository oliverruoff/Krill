"""Settings models and persistence helpers for the shared braindump SQLite database."""

import asyncio
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BRAINDUMP_PATH = BASE_DIR / "data" / "braindump.db"
BRAINDUMP_PATH = Path(os.getenv("KRILL_BRAINDUMP_PATH", str(DEFAULT_BRAINDUMP_PATH))).resolve()
BRAINDUMP_BACKUP_PATH = BRAINDUMP_PATH.with_suffix(".db.bak")
DATA_DIR = BRAINDUMP_PATH.parent
_DB_LOCK = asyncio.Lock()
SENSITIVE_KEYWORDS = {
    "api_key",
    "token",
    "secret",
    "password",
    "private_key",
    "ssh_private",
}

# Pydantic models remain the source of truth for the application layer
class ProviderConfig(BaseModel):
    api_key: str = ""
    model: str = ""


class MemoryEntry(BaseModel):
    content: str = Field(default="", max_length=200)
    created_at: str = ""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(default="", max_length=200000)
    timestamp: str = ""
    system_type: str = ""
    tool_usage: list[dict[str, str]] = Field(default_factory=list)
    request_id: str = ""
    status: str = ""


class ChatSession(BaseModel):
    id: str
    title: str = Field(default="New chat", max_length=120)
    type: Literal["normal"] = "normal"
    messages: list[ChatMessage] = Field(default_factory=list)
    memory_block: str = Field(default="", max_length=8000)
    total_tokens_used: int = Field(default=0, ge=0)
    collapse_system_trace: bool = True


class McpConfig(BaseModel):
    enabled: bool = False
    params: dict[str, str] = Field(default_factory=dict)


class IntegrationConfig(BaseModel):
    enabled: bool = False
    params: dict[str, str] = Field(default_factory=dict)


class DailyTokenUsage(BaseModel):
    date: str
    tokens: int = Field(default=0, ge=0)


class TelegramState(BaseModel):
    owner_user_id: str = ""
    last_update_id: int = Field(default=0, ge=0)


class Settings(BaseModel):
    bot_name: str = Field(default="MyBot", max_length=15)
    system_prompt: str = Field(default="Talk english. Be playful, friendly and use emojis! :).", max_length=200)
    setup_completed: bool = False
    active_provider_id: str = ""
    active_model_id: str = ""
    provider_configs: dict[str, ProviderConfig] = Field(default_factory=dict)
    core_memories: list[MemoryEntry] = Field(default_factory=list)
    normal_memories: list[MemoryEntry] = Field(default_factory=list)
    chats: list[ChatSession] = Field(default_factory=list)
    mcp_configs: dict[str, McpConfig] = Field(default_factory=dict)
    integration_configs: dict[str, IntegrationConfig] = Field(default_factory=dict)
    tool_max_recursion: int = Field(default=6, ge=1, le=20)
    tool_timeout_seconds: int = Field(default=45, ge=5, le=300)
    daily_token_usage: list[DailyTokenUsage] = Field(default_factory=list)
    active_chat_id: str = ""
    telegram_state: TelegramState = Field(default_factory=TelegramState)


def _get_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings_core (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          bot_name TEXT NOT NULL DEFAULT 'MyBot',
          system_prompt TEXT NOT NULL DEFAULT 'Talk english. Be playful, friendly and use emojis! :).',
          setup_completed INTEGER NOT NULL DEFAULT 0 CHECK (setup_completed IN (0,1)),
          active_provider_id TEXT NOT NULL DEFAULT '',
          active_model_id TEXT NOT NULL DEFAULT '',
          active_chat_id TEXT NOT NULL DEFAULT '',
          tool_max_recursion INTEGER NOT NULL DEFAULT 6,
          tool_timeout_seconds INTEGER NOT NULL DEFAULT 45
        );

        CREATE TABLE IF NOT EXISTS provider_configs (
          provider_id TEXT PRIMARY KEY,
          api_key TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS memories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          memory_type TEXT NOT NULL CHECK (memory_type IN ('core','normal')),
          content TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type, id);

        CREATE TABLE IF NOT EXISTS chats (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL DEFAULT 'New chat',
          type TEXT NOT NULL DEFAULT 'normal' CHECK (type = 'normal'),
          memory_block TEXT NOT NULL DEFAULT '',
          total_tokens_used INTEGER NOT NULL DEFAULT 0,
          collapse_system_trace INTEGER NOT NULL DEFAULT 1 CHECK (collapse_system_trace IN (0,1))
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          chat_id TEXT NOT NULL,
          seq INTEGER NOT NULL,
          role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
          content TEXT NOT NULL DEFAULT '',
          timestamp TEXT NOT NULL DEFAULT '',
          system_type TEXT NOT NULL DEFAULT '',
          request_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT '',
          FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
          UNIQUE (chat_id, seq)
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_seq ON chat_messages(chat_id, seq);

        CREATE TABLE IF NOT EXISTS message_tool_usage (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          message_id INTEGER NOT NULL,
          seq INTEGER NOT NULL,
          mcp_id TEXT NOT NULL,
          mcp_label TEXT NOT NULL DEFAULT '',
          tool_id TEXT NOT NULL,
          tool_label TEXT NOT NULL DEFAULT '',
          FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE CASCADE,
          UNIQUE (message_id, seq)
        );
        CREATE INDEX IF NOT EXISTS idx_tool_usage_message_seq ON message_tool_usage(message_id, seq);

        CREATE TABLE IF NOT EXISTS mcp_configs (
          mcp_id TEXT PRIMARY KEY,
          enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1))
        );

        CREATE TABLE IF NOT EXISTS mcp_config_params (
          mcp_id TEXT NOT NULL,
          param_key TEXT NOT NULL,
          param_value TEXT NOT NULL DEFAULT '',
          PRIMARY KEY (mcp_id, param_key),
          FOREIGN KEY (mcp_id) REFERENCES mcp_configs(mcp_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS integration_configs (
          integration_id TEXT PRIMARY KEY,
          enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1))
        );

        CREATE TABLE IF NOT EXISTS integration_config_params (
          integration_id TEXT NOT NULL,
          param_key TEXT NOT NULL,
          param_value TEXT NOT NULL DEFAULT '',
          PRIMARY KEY (integration_id, param_key),
          FOREIGN KEY (integration_id) REFERENCES integration_configs(integration_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS daily_token_usage (
          date TEXT PRIMARY KEY,
          tokens INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS telegram_state (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          owner_user_id TEXT NOT NULL DEFAULT '',
          last_update_id INTEGER NOT NULL DEFAULT 0
        );

        INSERT OR IGNORE INTO settings_core (id) VALUES (1);
        INSERT OR IGNORE INTO telegram_state (id) VALUES (1);
    """)
    conn.commit()


async def ensure_settings_file() -> None:
    await asyncio.to_thread(DATA_DIR.mkdir, parents=True, exist_ok=True)
    async with _DB_LOCK:
        conn = await asyncio.to_thread(_get_conn, BRAINDUMP_PATH)
        try:
            await asyncio.to_thread(_init_schema, conn)
        finally:
            await asyncio.to_thread(conn.close)


async def load_settings() -> Settings:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_load_settings_sync)


def _load_settings_sync() -> Settings:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        # 1. Core
        core = conn.execute("SELECT * FROM settings_core WHERE id = 1").fetchone()
        
        # 2. Providers
        providers = {}
        for row in conn.execute("SELECT * FROM provider_configs"):
            providers[row["provider_id"]] = ProviderConfig(api_key=row["api_key"], model=row["model"])
        
        # 3. Memories
        core_memories = []
        normal_memories = []
        for row in conn.execute("SELECT * FROM memories ORDER BY id ASC"):
            entry = MemoryEntry(content=row["content"], created_at=row["created_at"])
            if row["memory_type"] == "core":
                core_memories.append(entry)
            else:
                normal_memories.append(entry)
        
        # 4. Chats
        chats = []
        for chat_row in conn.execute("SELECT * FROM chats"):
            messages = []
            msg_cursor = conn.execute("SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY seq ASC", (chat_row["id"],))
            for msg_row in msg_cursor:
                tools = []
                tool_cursor = conn.execute("SELECT * FROM message_tool_usage WHERE message_id = ? ORDER BY seq ASC", (msg_row["id"],))
                for tool_row in tool_cursor:
                    tools.append({
                        "mcp_id": tool_row["mcp_id"],
                        "mcp_label": tool_row["mcp_label"],
                        "tool_id": tool_row["tool_id"],
                        "tool_label": tool_row["tool_label"],
                    })
                messages.append(ChatMessage(
                    role=msg_row["role"],
                    content=msg_row["content"],
                    timestamp=msg_row["timestamp"],
                    system_type=msg_row["system_type"],
                    tool_usage=tools,
                    request_id=msg_row["request_id"],
                    status=msg_row["status"]
                ))
            
            chats.append(ChatSession(
                id=chat_row["id"],
                title=chat_row["title"],
                type=chat_row["type"],
                messages=messages,
                memory_block=chat_row["memory_block"],
                total_tokens_used=chat_row["total_tokens_used"],
                collapse_system_trace=bool(chat_row["collapse_system_trace"])
            ))
        
        # 5. MCPs
        mcp_configs = {}
        for row in conn.execute("SELECT * FROM mcp_configs"):
            params = {r["param_key"]: r["param_value"] for r in conn.execute("SELECT * FROM mcp_config_params WHERE mcp_id = ?", (row["mcp_id"],))}
            mcp_configs[row["mcp_id"]] = McpConfig(enabled=bool(row["enabled"]), params=params)
        
        # 6. Integrations
        integration_configs = {}
        for row in conn.execute("SELECT * FROM integration_configs"):
            params = {r["param_key"]: r["param_value"] for r in conn.execute("SELECT * FROM integration_config_params WHERE integration_id = ?", (row["integration_id"],))}
            integration_configs[row["integration_id"]] = IntegrationConfig(enabled=bool(row["enabled"]), params=params)
            
        # 7. Usage
        usage = [DailyTokenUsage(date=r["date"], tokens=r["tokens"]) for r in conn.execute("SELECT * FROM daily_token_usage ORDER BY date ASC")]
        
        # 8. Telegram
        tg = conn.execute("SELECT * FROM telegram_state WHERE id = 1").fetchone()
        telegram_state = TelegramState(owner_user_id=tg["owner_user_id"], last_update_id=tg["last_update_id"])
        
        return Settings(
            bot_name=core["bot_name"],
            system_prompt=core["system_prompt"],
            setup_completed=bool(core["setup_completed"]),
            active_provider_id=core["active_provider_id"],
            active_model_id=core["active_model_id"],
            active_chat_id=core["active_chat_id"],
            tool_max_recursion=core["tool_max_recursion"],
            tool_timeout_seconds=core["tool_timeout_seconds"],
            provider_configs=providers,
            core_memories=core_memories,
            normal_memories=normal_memories,
            chats=chats,
            mcp_configs=mcp_configs,
            integration_configs=integration_configs,
            daily_token_usage=usage,
            telegram_state=telegram_state
        )
    finally:
        conn.close()


async def save_settings(settings: Settings) -> Settings:
    await ensure_settings_file()
    async with _DB_LOCK:
        normalized = _sync_active_selection(settings)
        await asyncio.to_thread(_save_settings_sync, normalized)
        await asyncio.to_thread(_check_backup)
        return normalized


def _save_settings_sync(settings: Settings) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        conn.execute("BEGIN TRANSACTION")
        
        # 1. Core
        conn.execute("""
            UPDATE settings_core SET 
                bot_name = ?, system_prompt = ?, setup_completed = ?, 
                active_provider_id = ?, active_model_id = ?, active_chat_id = ?,
                tool_max_recursion = ?, tool_timeout_seconds = ?
            WHERE id = 1
        """, (
            settings.bot_name, settings.system_prompt, int(settings.setup_completed),
            settings.active_provider_id, settings.active_model_id, settings.active_chat_id,
            settings.tool_max_recursion, settings.tool_timeout_seconds
        ))
        
        # 2. Providers
        conn.execute("DELETE FROM provider_configs")
        for pid, conf in settings.provider_configs.items():
            conn.execute("INSERT INTO provider_configs (provider_id, api_key, model) VALUES (?, ?, ?)", (pid, conf.api_key, conf.model))
            
        # 3. Memories
        conn.execute("DELETE FROM memories")
        for m in settings.core_memories:
            conn.execute("INSERT INTO memories (memory_type, content, created_at) VALUES ('core', ?, ?)", (m.content, m.created_at))
        for m in settings.normal_memories:
            conn.execute("INSERT INTO memories (memory_type, content, created_at) VALUES ('normal', ?, ?)", (m.content, m.created_at))
            
        # 4. Chats
        conn.execute("DELETE FROM message_tool_usage")
        conn.execute("DELETE FROM chat_messages")
        conn.execute("DELETE FROM chats")
        for chat in settings.chats:
            conn.execute("INSERT INTO chats (id, title, type, memory_block, total_tokens_used, collapse_system_trace) VALUES (?, ?, ?, ?, ?, ?)",
                (chat.id, chat.title, chat.type, chat.memory_block, chat.total_tokens_used, int(chat.collapse_system_trace)))
            for i, msg in enumerate(chat.messages):
                cursor = conn.execute("INSERT INTO chat_messages (chat_id, seq, role, content, timestamp, system_type, request_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (chat.id, i, msg.role, msg.content, msg.timestamp, msg.system_type, msg.request_id, msg.status))
                msg_id = cursor.lastrowid
                for j, tool in enumerate(msg.tool_usage):
                    conn.execute("INSERT INTO message_tool_usage (message_id, seq, mcp_id, mcp_label, tool_id, tool_label) VALUES (?, ?, ?, ?, ?, ?)",
                        (msg_id, j, tool["mcp_id"], tool.get("mcp_label", ""), tool["tool_id"], tool.get("tool_label", "")))
                        
        # 5. MCPs
        conn.execute("DELETE FROM mcp_config_params")
        conn.execute("DELETE FROM mcp_configs")
        for mid, conf in settings.mcp_configs.items():
            conn.execute("INSERT INTO mcp_configs (mcp_id, enabled) VALUES (?, ?)", (mid, int(conf.enabled)))
            for k, v in conf.params.items():
                conn.execute("INSERT INTO mcp_config_params (mcp_id, param_key, param_value) VALUES (?, ?, ?)", (mid, k, v))
                
        # 6. Integrations
        conn.execute("DELETE FROM integration_config_params")
        conn.execute("DELETE FROM integration_configs")
        for iid, conf in settings.integration_configs.items():
            conn.execute("INSERT INTO integration_configs (integration_id, enabled) VALUES (?, ?)", (iid, int(conf.enabled)))
            for k, v in conf.params.items():
                conn.execute("INSERT INTO integration_config_params (integration_id, param_key, param_value) VALUES (?, ?, ?)", (iid, k, v))
                
        # 7. Usage
        conn.execute("DELETE FROM daily_token_usage")
        for item in settings.daily_token_usage:
            conn.execute("INSERT INTO daily_token_usage (date, tokens) VALUES (?, ?)", (item.date, item.tokens))
            
        # 8. Telegram
        conn.execute("UPDATE telegram_state SET owner_user_id = ?, last_update_id = ? WHERE id = 1",
            (settings.telegram_state.owner_user_id, settings.telegram_state.last_update_id))
            
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _check_backup() -> None:
    if not BRAINDUMP_PATH.exists():
        return
    
    should_backup = True
    if BRAINDUMP_BACKUP_PATH.exists():
        mtime = BRAINDUMP_BACKUP_PATH.stat().st_mtime
        if datetime.now().timestamp() - mtime < 1800: # 30 mins
            should_backup = False
            
    if should_backup:
        try:
            # We use the SQLite backup API for a clean copy while possibly WAL is active
            src = _get_conn(BRAINDUMP_PATH)
            dst = _get_conn(BRAINDUMP_BACKUP_PATH)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
        except Exception:
            pass


def _sync_active_selection(settings: Settings) -> Settings:
    provider_configs = settings.provider_configs
    active_provider_id = settings.active_provider_id

    if active_provider_id and active_provider_id not in provider_configs:
        active_provider_id = ""

    if not active_provider_id and provider_configs:
        active_provider_id = next(iter(provider_configs.keys()))

    active_model_id = ""
    if active_provider_id:
        active_config = provider_configs.get(active_provider_id)
        if active_config is not None:
            active_model_id = active_config.model.strip()

    chat_ids = {chat.id for chat in settings.chats if isinstance(chat.id, str) and chat.id.strip()}
    active_chat_id = settings.active_chat_id.strip() if isinstance(settings.active_chat_id, str) else ""
    if active_chat_id and active_chat_id not in chat_ids:
        active_chat_id = ""
    if not active_chat_id and settings.chats:
        active_chat_id = settings.chats[0].id

    return settings.model_copy(
        update={
            "active_provider_id": active_provider_id,
            "active_model_id": active_model_id,
            "active_chat_id": active_chat_id,
        }
    )


async def create_braindump_snapshot(target_path: Path) -> None:
    """Creates a consistent SQLite backup of the current state."""
    await ensure_settings_file()
    async with _DB_LOCK:
        src = await asyncio.to_thread(_get_conn, BRAINDUMP_PATH)
        dst = await asyncio.to_thread(_get_conn, target_path)
        try:
            await asyncio.to_thread(src.backup, dst)
        finally:
            await asyncio.to_thread(dst.close)
            await asyncio.to_thread(src.close)


async def import_braindump_db(source_path: Path) -> None:
    """Replaces the current database with the provided one."""
    await ensure_settings_file()
    async with _DB_LOCK:
        # 1. Validate the new file is a valid SQLite DB and run migrations on it
        conn = await asyncio.to_thread(_get_conn, source_path)
        try:
            await asyncio.to_thread(_init_schema, conn)
        finally:
            await asyncio.to_thread(conn.close)
            
        # 2. Atomic swap
        await asyncio.to_thread(shutil.copyfile, source_path, BRAINDUMP_PATH)


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return '"' + escaped + '"'


def _is_sensitive_column(column_name: str) -> bool:
    lowered = column_name.lower()
    return any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)


def _mask_value(value: object) -> object:
    if value is None:
        return None
    text = str(value)
    if not text:
        return ""
    if len(text) <= 4:
        return "****"
    return f"{text[:2]}***{text[-2:]}"


def _view_braindump_sync(show_secrets: bool) -> dict[str, object]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC"
        ).fetchall()
        table_names = [str(row["name"]) for row in table_rows]

        tables: list[dict[str, object]] = []
        for table_name in table_names:
            quoted = _quote_identifier(table_name)
            column_rows = conn.execute(f"PRAGMA table_info({quoted})").fetchall()
            columns = [
                {
                    "name": str(column["name"]),
                    "type": str(column["type"] or ""),
                    "notnull": bool(column["notnull"]),
                    "pk": bool(column["pk"]),
                }
                for column in column_rows
            ]

            row_count = conn.execute(f"SELECT COUNT(*) AS count FROM {quoted}").fetchone()
            total_rows = int(row_count["count"] if row_count else 0)

            result_rows = conn.execute(f"SELECT * FROM {quoted}").fetchall()
            entries: list[dict[str, object]] = []
            for raw_row in result_rows:
                entry: dict[str, object] = {}
                for key in raw_row.keys():
                    raw_value: Any = raw_row[key]
                    if show_secrets or not _is_sensitive_column(str(key)):
                        entry[str(key)] = raw_value
                    else:
                        entry[str(key)] = _mask_value(raw_value)
                entries.append(entry)

            tables.append(
                {
                    "name": table_name,
                    "columns": columns,
                    "row_count": total_rows,
                    "rows": entries,
                }
            )

        return {
            "ok": True,
            "show_secrets": show_secrets,
            "table_count": len(tables),
            "tables": tables,
        }
    finally:
        conn.close()


async def view_braindump(*, show_secrets: bool = False) -> dict[str, object]:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_view_braindump_sync, show_secrets)
