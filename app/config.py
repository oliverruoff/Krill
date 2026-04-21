"""Settings models and persistence helpers for the shared braindump SQLite database."""

import asyncio
import json
import os
import re
import shutil
import sqlite3
import uuid
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BRAINDUMP_PATH = BASE_DIR / "data" / "braindump.db"
BRAINDUMP_PATH = Path(os.getenv("KRILL_BRAINDUMP_PATH", str(DEFAULT_BRAINDUMP_PATH))).resolve()
BRAINDUMP_BACKUP_PATH = BRAINDUMP_PATH.with_suffix(".db.bak")
DATA_DIR = BRAINDUMP_PATH.parent
SCRIPTS_DIR = (DATA_DIR / "scripts").resolve()
_DB_LOCK = asyncio.Lock()
SENSITIVE_KEYWORDS = {
    "api_key",
    "token",
    "secret",
    "password",
    "password_hash",
    "session_hash",
    "session_id",
    "private_key",
    "ssh_private",
}
SCRIPTS_DISABLED_TITLES_PARAM = "disabled_script_titles"
_SCRIPTS_ENABLED_TITLES_LEGACY_PARAM = "enabled_script_titles"

# Pydantic models remain the source of truth for the application layer
class ProviderConfig(BaseModel):
    api_key: str = ""
    model: str = ""


class MemoryEntry(BaseModel):
    content: str = Field(default="", max_length=1000000)
    created_at: str = ""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(default="", max_length=1000000)
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
    hidden_from_history: bool = False


class McpConfig(BaseModel):
    enabled: bool = False
    params: dict[str, str] = Field(default_factory=dict)


class IntegrationConfig(BaseModel):
    enabled: bool = False
    params: dict[str, str] = Field(default_factory=dict)


class DailyTokenUsage(BaseModel):
    date: str
    tokens: int = Field(default=0, ge=0)


class ChatStateSnapshot(BaseModel):
    chats: list[ChatSession] = Field(default_factory=list)
    active_chat_id: str = ""
    daily_token_usage: list[DailyTokenUsage] = Field(default_factory=list)


class TelegramState(BaseModel):
    owner_user_id: str = ""
    owner_chat_id: str = ""
    last_update_id: int = Field(default=0, ge=0)


TimedJobInterval = Literal[
    "daily",
    "weekly",
    "monthly",
    "once",
    "hourly",
    "every_2_hours",
    "every_30_min",
    "every_15_min",
    "every_10_min",
    "every_5_min",
]


class TimedJob(BaseModel):
    id: str
    title: str = Field(default="", max_length=120)
    prompt: str = Field(default="", max_length=5000)
    interval: TimedJobInterval = "daily"
    start_date: str = Field(default="")
    time_of_day: str = Field(default="00:00")
    timezone: str = Field(default="UTC")
    timezone_offset_minutes: int = Field(default=0, ge=-840, le=840)
    enabled: bool = False
    output_decision_enabled: bool = False
    channels: list[str] = Field(default_factory=list)
    provider_id: str = ""
    model: str = ""
    next_run_at: str = ""
    last_run_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class ScriptDefinition(BaseModel):
    id: str
    title: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=1024)
    instructions: str = Field(default="", max_length=5000)
    python_requirements: str = Field(default="", max_length=500)
    body: str = Field(default="")
    file_name: str = Field(default="", max_length=100)
    created_at: str = ""
    updated_at: str = ""


class Settings(BaseModel):
    bot_name: str = Field(default="MyBot", max_length=15)
    system_prompt: str = Field(default="Talk english. Be playful, friendly and use emojis! :).", max_length=400)
    user_full_name: str = Field(default="", max_length=120)
    user_call_name: str = Field(default="", max_length=60)
    setup_completed: bool = False
    active_provider_id: str = ""
    active_model_id: str = ""
    provider_configs: dict[str, ProviderConfig] = Field(default_factory=dict)
    core_memories: list[MemoryEntry] = Field(default_factory=list)
    normal_memories: list[MemoryEntry] = Field(default_factory=list)
    chats: list[ChatSession] = Field(default_factory=list)
    mcp_configs: dict[str, McpConfig] = Field(default_factory=dict)
    integration_configs: dict[str, IntegrationConfig] = Field(default_factory=dict)
    tool_max_recursion: int = Field(default=8, ge=1, le=20)
    tool_timeout_seconds: int = Field(default=90, ge=5, le=300)
    memory_extraction_interval: int = Field(default=10, ge=1, le=500)
    user_message_count: int = Field(default=0, ge=0)
    daily_token_usage: list[DailyTokenUsage] = Field(default_factory=list)
    active_chat_id: str = ""
    timed_job_auth_alert_provider_ids: list[str] = Field(default_factory=list)
    telegram_state: TelegramState = Field(default_factory=TelegramState)
    theme: Literal["light", "dark", "business"] = "light"
    last_daily_summary_date: str = ""


class ShortTermMemoryItem(BaseModel):
    id: int
    content: str
    memory_type: Literal["core", "normal"]
    source_channel: str = ""
    source_chat_id: str = ""
    source_request_id: str = ""
    status: Literal["pending", "accepted", "rejected"] = "pending"
    created_at: str


def _parse_script_title_set_from_param(config_params: dict[str, str] | None, param_name: str) -> set[str]:
    if not isinstance(config_params, dict):
        return set()

    raw_value = config_params.get(param_name, "")
    if not isinstance(raw_value, str):
        return set()

    trimmed = raw_value.strip()
    if not trimmed:
        return set()

    try:
        parsed = json.loads(trimmed)
    except Exception:
        return set()

    if not isinstance(parsed, list):
        return set()

    titles: set[str] = set()
    for item in parsed:
        title = str(item or "").strip()
        if not title:
            continue
        titles.add(title)
    return titles


def is_script_title_enabled(script_title: str, config_params: dict[str, str] | None) -> bool:
    title = str(script_title or "").strip()
    if not title:
        return False

    disabled_titles = _parse_script_title_set_from_param(config_params, SCRIPTS_DISABLED_TITLES_PARAM)
    if title in disabled_titles:
        return False

    enabled_titles_legacy = _parse_script_title_set_from_param(config_params, _SCRIPTS_ENABLED_TITLES_LEGACY_PARAM)
    if enabled_titles_legacy and title not in enabled_titles_legacy:
        return False

    return True


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
          user_full_name TEXT NOT NULL DEFAULT '',
          user_call_name TEXT NOT NULL DEFAULT '',
          setup_completed INTEGER NOT NULL DEFAULT 0 CHECK (setup_completed IN (0,1)),
          active_provider_id TEXT NOT NULL DEFAULT '',
          active_model_id TEXT NOT NULL DEFAULT '',
          active_chat_id TEXT NOT NULL DEFAULT '',
          tool_max_recursion INTEGER NOT NULL DEFAULT 8,
          tool_timeout_seconds INTEGER NOT NULL DEFAULT 90,
          memory_extraction_interval INTEGER NOT NULL DEFAULT 10,
          user_message_count INTEGER NOT NULL DEFAULT 0,
          timed_job_auth_alert_provider_ids TEXT NOT NULL DEFAULT '[]',
          theme TEXT NOT NULL DEFAULT 'light'
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
          collapse_system_trace INTEGER NOT NULL DEFAULT 1 CHECK (collapse_system_trace IN (0,1)),
          hidden_from_history INTEGER NOT NULL DEFAULT 0 CHECK (hidden_from_history IN (0,1))
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
          owner_chat_id TEXT NOT NULL DEFAULT '',
          last_update_id INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS whatsapp_state (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          session_blob TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS auth_users (
          id TEXT PRIMARY KEY,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
          created_at TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_auth_users_username ON auth_users(username);

        CREATE TABLE IF NOT EXISTS auth_sessions (
          session_id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          session_hash TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT '',
          expires_at TEXT NOT NULL DEFAULT '',
          last_seen_at TEXT NOT NULL DEFAULT '',
          revoked_at TEXT NOT NULL DEFAULT '',
          ip TEXT NOT NULL DEFAULT '',
          FOREIGN KEY (user_id) REFERENCES auth_users(id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_sessions_hash ON auth_sessions(session_hash);
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);

        CREATE TABLE IF NOT EXISTS auth_ip_locks (
          ip TEXT PRIMARY KEY,
          failed_count INTEGER NOT NULL DEFAULT 0,
          first_failed_at TEXT NOT NULL DEFAULT '',
          last_failed_at TEXT NOT NULL DEFAULT '',
          banned_until TEXT NOT NULL DEFAULT ''
        );
        
        INSERT OR IGNORE INTO settings_core (id) VALUES (1);
        INSERT OR IGNORE INTO telegram_state (id) VALUES (1);
        INSERT OR IGNORE INTO whatsapp_state (id) VALUES (1);

        CREATE TABLE IF NOT EXISTS short_term_memories (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          content TEXT NOT NULL,
          memory_type TEXT NOT NULL CHECK (memory_type IN ('core', 'normal')),
          source_channel TEXT NOT NULL DEFAULT '',
          source_chat_id TEXT NOT NULL DEFAULT '',
          source_request_id TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
          created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_short_term_memories_status_created
          ON short_term_memories(status, created_at DESC);

        CREATE TABLE IF NOT EXISTS conversation_turns (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_channel TEXT NOT NULL DEFAULT '',
          source_chat_id TEXT NOT NULL DEFAULT '',
          user_message TEXT NOT NULL,
          assistant_message TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_conversation_turns_created ON conversation_turns(created_at DESC);

        CREATE TABLE IF NOT EXISTS timed_jobs (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL DEFAULT '',
          prompt TEXT NOT NULL DEFAULT '',
          interval_type TEXT NOT NULL DEFAULT 'daily' CHECK (interval_type IN ('daily', 'weekly', 'monthly', 'once', 'hourly', 'every_2_hours', 'every_30_min', 'every_15_min', 'every_10_min', 'every_5_min')),
          start_date TEXT NOT NULL DEFAULT '',
          time_of_day TEXT NOT NULL DEFAULT '00:00',
          timezone TEXT NOT NULL DEFAULT 'UTC',
          timezone_offset_minutes INTEGER NOT NULL DEFAULT 0,
          enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
          output_decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK (output_decision_enabled IN (0,1)),
          channels_json TEXT NOT NULL DEFAULT '[]',
          provider_id TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL DEFAULT '',
          next_run_at TEXT NOT NULL DEFAULT '',
          last_run_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_timed_jobs_next_run ON timed_jobs(enabled, next_run_at);

        CREATE TABLE IF NOT EXISTS scripts (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL DEFAULT '',
          description TEXT NOT NULL DEFAULT '',
          instructions TEXT NOT NULL DEFAULT '',
          requirements TEXT NOT NULL DEFAULT '',
          python_requirements TEXT NOT NULL DEFAULT '',
          body TEXT NOT NULL DEFAULT '',
          file_name TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT ''
        );
    """)

    _ensure_settings_core_column(conn, "memory_extraction_interval", "INTEGER NOT NULL DEFAULT 10")
    _ensure_settings_core_column(conn, "user_message_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_settings_core_column(conn, "user_full_name", "TEXT NOT NULL DEFAULT ''")
    _ensure_settings_core_column(conn, "user_call_name", "TEXT NOT NULL DEFAULT ''")
    _ensure_settings_core_column(conn, "timed_job_auth_alert_provider_ids", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_settings_core_column(conn, "theme", "TEXT NOT NULL DEFAULT 'light'")
    _ensure_settings_core_column(conn, "last_daily_summary_date", "TEXT NOT NULL DEFAULT ''")
    _ensure_chats_column(conn, "hidden_from_history", "INTEGER NOT NULL DEFAULT 0 CHECK (hidden_from_history IN (0,1))")
    _ensure_telegram_state_column(conn, "owner_chat_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_whatsapp_state_column(conn, "session_blob", "TEXT NOT NULL DEFAULT ''")
    _ensure_timed_jobs_column(conn, "timezone_offset_minutes", "INTEGER NOT NULL DEFAULT 0")
    _ensure_timed_jobs_column(conn, "output_decision_enabled", "INTEGER NOT NULL DEFAULT 0 CHECK (output_decision_enabled IN (0,1))")
    _ensure_timed_jobs_column(conn, "provider_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_timed_jobs_column(conn, "model", "TEXT NOT NULL DEFAULT ''")
    _ensure_scripts_column(conn, "python_requirements", "TEXT NOT NULL DEFAULT ''")
    _backfill_scripts_python_requirements(conn)
    _backfill_hidden_history_flags(conn)
    _ensure_timed_jobs_interval_constraint(conn)
    conn.commit()


def _ensure_settings_core_column(conn: sqlite3.Connection, column_name: str, definition: str) -> None:
    rows = conn.execute("PRAGMA table_info(settings_core)").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE settings_core ADD COLUMN {column_name} {definition}")


def _ensure_telegram_state_column(conn: sqlite3.Connection, column_name: str, definition: str) -> None:
    rows = conn.execute("PRAGMA table_info(telegram_state)").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE telegram_state ADD COLUMN {column_name} {definition}")


def _ensure_chats_column(conn: sqlite3.Connection, column_name: str, definition: str) -> None:
    rows = conn.execute("PRAGMA table_info(chats)").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE chats ADD COLUMN {column_name} {definition}")


def _backfill_hidden_history_flags(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE chats
        SET hidden_from_history = 1
        WHERE hidden_from_history = 0
          AND id IN (
              SELECT DISTINCT chat_id
              FROM chat_messages
              WHERE role = 'system' AND system_type = 'timed_job_hidden_debug'
          )
        """
    )


def _ensure_timed_jobs_column(conn: sqlite3.Connection, column_name: str, definition: str) -> None:
    rows = conn.execute("PRAGMA table_info(timed_jobs)").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE timed_jobs ADD COLUMN {column_name} {definition}")


def _ensure_scripts_column(conn: sqlite3.Connection, column_name: str, definition: str) -> None:
    rows = conn.execute("PRAGMA table_info(scripts)").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE scripts ADD COLUMN {column_name} {definition}")


def _backfill_scripts_python_requirements(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE scripts
        SET python_requirements = requirements
        WHERE COALESCE(TRIM(python_requirements), '') = ''
          AND COALESCE(TRIM(requirements), '') <> ''
        """
    )


def _ensure_timed_jobs_interval_constraint(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'timed_jobs'"
    ).fetchone()
    if row is None:
        return

    table_sql = str(row["sql"] or "").lower()
    required_values = (
        "hourly",
        "every_2_hours",
        "every_30_min",
        "every_15_min",
        "every_10_min",
        "every_5_min",
    )
    if all(value in table_sql for value in required_values):
        return

    conn.execute("ALTER TABLE timed_jobs RENAME TO timed_jobs_legacy")
    conn.execute(
        """
        CREATE TABLE timed_jobs (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL DEFAULT '',
          prompt TEXT NOT NULL DEFAULT '',
          interval_type TEXT NOT NULL DEFAULT 'daily' CHECK (
            interval_type IN (
              'daily',
              'weekly',
              'monthly',
              'once',
              'hourly',
              'every_2_hours',
              'every_30_min',
              'every_15_min',
              'every_10_min',
              'every_5_min'
            )
          ),
          start_date TEXT NOT NULL DEFAULT '',
          time_of_day TEXT NOT NULL DEFAULT '00:00',
          timezone TEXT NOT NULL DEFAULT 'UTC',
          timezone_offset_minutes INTEGER NOT NULL DEFAULT 0,
          enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
          output_decision_enabled INTEGER NOT NULL DEFAULT 0 CHECK (output_decision_enabled IN (0,1)),
          channels_json TEXT NOT NULL DEFAULT '[]',
          provider_id TEXT NOT NULL DEFAULT '',
          model TEXT NOT NULL DEFAULT '',
          next_run_at TEXT NOT NULL DEFAULT '',
          last_run_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO timed_jobs (
          id, title, prompt, interval_type, start_date, time_of_day, timezone,
          timezone_offset_minutes, enabled, output_decision_enabled, channels_json, provider_id, model, next_run_at, last_run_at, created_at, updated_at
        )
        SELECT
          id, title, prompt, interval_type, start_date, time_of_day, timezone,
          timezone_offset_minutes, enabled, 0, channels_json, '', '', next_run_at, last_run_at, created_at, updated_at
        FROM timed_jobs_legacy
        """
    )
    conn.execute("DROP TABLE timed_jobs_legacy")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_timed_jobs_next_run ON timed_jobs(enabled, next_run_at)")


def _ensure_whatsapp_state_column(conn: sqlite3.Connection, column_name: str, definition: str) -> None:
    rows = conn.execute("PRAGMA table_info(whatsapp_state)").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE whatsapp_state ADD COLUMN {column_name} {definition}")


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


async def load_chat_state() -> ChatStateSnapshot:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_load_chat_state_sync)


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
            msg_cursor = conn.execute(
                "SELECT * FROM chat_messages WHERE chat_id = ? AND role != 'system' ORDER BY seq ASC",
                (chat_row["id"],),
            )
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
                collapse_system_trace=bool(chat_row["collapse_system_trace"]),
                hidden_from_history=bool(chat_row["hidden_from_history"]) if "hidden_from_history" in chat_row.keys() else False,
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
        telegram_state = TelegramState(
            owner_user_id=tg["owner_user_id"],
            owner_chat_id=tg["owner_chat_id"],
            last_update_id=tg["last_update_id"],
        )
        
        return Settings(
            bot_name=core["bot_name"],
            system_prompt=core["system_prompt"],
            user_full_name=core["user_full_name"],
            user_call_name=core["user_call_name"],
            setup_completed=bool(core["setup_completed"]),
            active_provider_id=core["active_provider_id"],
            active_model_id=core["active_model_id"],
            active_chat_id=core["active_chat_id"],
            tool_max_recursion=core["tool_max_recursion"],
            tool_timeout_seconds=core["tool_timeout_seconds"],
            memory_extraction_interval=core["memory_extraction_interval"],
            user_message_count=core["user_message_count"],
            provider_configs=providers,
            core_memories=core_memories,
            normal_memories=normal_memories,
            chats=chats,
            mcp_configs=mcp_configs,
            integration_configs=integration_configs,
            daily_token_usage=usage,
            timed_job_auth_alert_provider_ids=_deserialize_provider_id_list(core["timed_job_auth_alert_provider_ids"]),
            telegram_state=telegram_state,
            theme=_normalize_theme_mode(core["theme"]),
            last_daily_summary_date=str(core["last_daily_summary_date"]) if "last_daily_summary_date" in core.keys() else "",
        )
    finally:
        conn.close()


def _load_chat_state_sync() -> ChatStateSnapshot:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        core = conn.execute("SELECT active_chat_id FROM settings_core WHERE id = 1").fetchone()
        chats = _load_chats_from_conn(conn)
        usage = [DailyTokenUsage(date=row["date"], tokens=row["tokens"]) for row in conn.execute("SELECT * FROM daily_token_usage ORDER BY date ASC")]
        active_chat_id = core["active_chat_id"] if core is not None else ""
        return ChatStateSnapshot(
            chats=chats,
            active_chat_id=_normalize_active_chat_id(active_chat_id, chats),
            daily_token_usage=usage,
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


async def get_timed_job_auth_alert_provider_ids() -> list[str]:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_get_timed_job_auth_alert_provider_ids_sync)


async def add_timed_job_auth_alert_provider_id(provider_id: str) -> list[str]:
    normalized_provider_id = str(provider_id or "").strip()
    if not normalized_provider_id:
        return await get_timed_job_auth_alert_provider_ids()
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_update_timed_job_auth_alert_provider_ids_sync, normalized_provider_id, True)


async def clear_timed_job_auth_alert_provider_id(provider_id: str) -> list[str]:
    normalized_provider_id = str(provider_id or "").strip()
    if not normalized_provider_id:
        return await get_timed_job_auth_alert_provider_ids()
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_update_timed_job_auth_alert_provider_ids_sync, normalized_provider_id, False)


async def save_chat_state(
    chats: list[ChatSession],
    active_chat_id: str,
    daily_token_usage: list[DailyTokenUsage],
    *,
    preserve_active_chat_id: bool = False,
) -> ChatStateSnapshot:
    await ensure_settings_file()
    async with _DB_LOCK:
        normalized_active_chat_id = _normalize_active_chat_id(active_chat_id, chats)
        normalized = ChatStateSnapshot(
            chats=chats,
            active_chat_id=normalized_active_chat_id,
            daily_token_usage=daily_token_usage,
        )
        await asyncio.to_thread(_save_chat_state_sync, normalized, preserve_active_chat_id)
        await asyncio.to_thread(_check_backup)
        return normalized


async def update_chat_title(chat_id: str, title: str) -> bool:
    """Update the title of a single chat without rewriting all tables."""
    clean_id = str(chat_id or "").strip()
    clean_title = str(title or "").strip()[:120]
    if not clean_id or not clean_title:
        return False
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_update_chat_title_sync, clean_id, clean_title)


def _update_chat_title_sync(chat_id: str, title: str) -> bool:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        cursor = conn.execute("UPDATE chats SET title = ? WHERE id = ?", (title, chat_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def _save_settings_sync(settings: Settings) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        conn.execute("BEGIN TRANSACTION")
        
        # 1. Core
        conn.execute("""
            UPDATE settings_core SET 
                bot_name = ?, system_prompt = ?, user_full_name = ?, user_call_name = ?, setup_completed = ?, 
                active_provider_id = ?, active_model_id = ?, active_chat_id = ?,
                tool_max_recursion = ?, tool_timeout_seconds = ?,
                memory_extraction_interval = ?, timed_job_auth_alert_provider_ids = ?, theme = ?,
                last_daily_summary_date = ?
            WHERE id = 1
        """, (
            settings.bot_name, settings.system_prompt, settings.user_full_name, settings.user_call_name, int(settings.setup_completed),
            settings.active_provider_id, settings.active_model_id, settings.active_chat_id,
            settings.tool_max_recursion, settings.tool_timeout_seconds,
            settings.memory_extraction_interval,
            _serialize_provider_id_list(settings.timed_job_auth_alert_provider_ids),
            _normalize_theme_mode(settings.theme),
            settings.last_daily_summary_date,
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
            conn.execute(
                "INSERT INTO chats (id, title, type, memory_block, total_tokens_used, collapse_system_trace, hidden_from_history) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    chat.id,
                    chat.title,
                    chat.type,
                    chat.memory_block,
                    chat.total_tokens_used,
                    int(chat.collapse_system_trace),
                    int(chat.hidden_from_history),
                ),
            )
            seq = 0
            for msg in chat.messages:
                if msg.role == "system":
                    continue
                cursor = conn.execute("INSERT INTO chat_messages (chat_id, seq, role, content, timestamp, system_type, request_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (chat.id, seq, msg.role, msg.content, msg.timestamp, msg.system_type, msg.request_id, msg.status))
                msg_id = cursor.lastrowid
                for j, tool in enumerate(msg.tool_usage):
                    conn.execute("INSERT INTO message_tool_usage (message_id, seq, mcp_id, mcp_label, tool_id, tool_label) VALUES (?, ?, ?, ?, ?, ?)",
                        (msg_id, j, tool["mcp_id"], tool.get("mcp_label", ""), tool["tool_id"], tool.get("tool_label", "")))
                seq += 1
                        
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
        conn.execute(
            "UPDATE telegram_state SET owner_user_id = ?, owner_chat_id = ?, last_update_id = ? WHERE id = 1",
            (
                settings.telegram_state.owner_user_id,
                settings.telegram_state.owner_chat_id,
                settings.telegram_state.last_update_id,
            ),
        )
            
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _save_chat_state_sync(snapshot: ChatStateSnapshot, preserve_active_chat_id: bool = False) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        conn.execute("BEGIN TRANSACTION")
        active_chat_id = snapshot.active_chat_id
        if preserve_active_chat_id:
            row = conn.execute("SELECT active_chat_id FROM settings_core WHERE id = 1").fetchone()
            persisted_active_chat_id = str(row["active_chat_id"]) if row is not None else ""
            active_chat_id = _normalize_active_chat_id(persisted_active_chat_id, snapshot.chats)
        conn.execute(
            "UPDATE settings_core SET active_chat_id = ? WHERE id = 1",
            (active_chat_id,),
        )
        _rewrite_chat_tables(conn, snapshot.chats)
        conn.execute("DELETE FROM daily_token_usage")
        for item in snapshot.daily_token_usage:
            conn.execute("INSERT INTO daily_token_usage (date, tokens) VALUES (?, ?)", (item.date, item.tokens))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_timed_job_auth_alert_provider_ids_sync() -> list[str]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute("SELECT timed_job_auth_alert_provider_ids FROM settings_core WHERE id = 1").fetchone()
        if row is None:
            return []
        return _deserialize_provider_id_list(row["timed_job_auth_alert_provider_ids"])
    finally:
        conn.close()


def _update_timed_job_auth_alert_provider_ids_sync(provider_id: str, add_provider: bool) -> list[str]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute("INSERT OR IGNORE INTO settings_core (id) VALUES (1)")
        row = conn.execute("SELECT timed_job_auth_alert_provider_ids FROM settings_core WHERE id = 1").fetchone()
        provider_ids = _deserialize_provider_id_list(row["timed_job_auth_alert_provider_ids"] if row is not None else "[]")
        provider_set = {entry for entry in provider_ids if entry}
        if add_provider:
            provider_set.add(provider_id)
        else:
            provider_set.discard(provider_id)
        normalized = sorted(provider_set)
        conn.execute(
            "UPDATE settings_core SET timed_job_auth_alert_provider_ids = ? WHERE id = 1",
            (_serialize_provider_id_list(normalized),),
        )
        conn.commit()
        return normalized
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_chats_from_conn(conn: sqlite3.Connection) -> list[ChatSession]:
    chats: list[ChatSession] = []
    for chat_row in conn.execute("SELECT * FROM chats"):
        messages = []
        msg_cursor = conn.execute(
            "SELECT * FROM chat_messages WHERE chat_id = ? AND role != 'system' ORDER BY seq ASC",
            (chat_row["id"],),
        )
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
                status=msg_row["status"],
            ))

        chats.append(ChatSession(
            id=chat_row["id"],
            title=chat_row["title"],
            type=chat_row["type"],
            messages=messages,
            memory_block=chat_row["memory_block"],
            total_tokens_used=chat_row["total_tokens_used"],
            collapse_system_trace=bool(chat_row["collapse_system_trace"]),
            hidden_from_history=bool(chat_row["hidden_from_history"]) if "hidden_from_history" in chat_row.keys() else False,
        ))
    return chats


def _rewrite_chat_tables(conn: sqlite3.Connection, chats: list[ChatSession]) -> None:
    conn.execute("DELETE FROM message_tool_usage")
    conn.execute("DELETE FROM chat_messages")
    conn.execute("DELETE FROM chats")
    for chat in chats:
        conn.execute(
            "INSERT INTO chats (id, title, type, memory_block, total_tokens_used, collapse_system_trace, hidden_from_history) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                chat.id,
                chat.title,
                chat.type,
                chat.memory_block,
                chat.total_tokens_used,
                int(chat.collapse_system_trace),
                int(chat.hidden_from_history),
            ),
        )
        seq = 0
        for msg in chat.messages:
            if msg.role == "system":
                continue
            cursor = conn.execute(
                "INSERT INTO chat_messages (chat_id, seq, role, content, timestamp, system_type, request_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chat.id, seq, msg.role, msg.content, msg.timestamp, msg.system_type, msg.request_id, msg.status),
            )
            msg_id = cursor.lastrowid
            for j, tool in enumerate(msg.tool_usage):
                conn.execute(
                    "INSERT INTO message_tool_usage (message_id, seq, mcp_id, mcp_label, tool_id, tool_label) VALUES (?, ?, ?, ?, ?, ?)",
                    (msg_id, j, tool["mcp_id"], tool.get("mcp_label", ""), tool["tool_id"], tool.get("tool_label", "")),
                )
            seq += 1


def _normalize_active_chat_id(active_chat_id: str, chats: list[ChatSession]) -> str:
    normalized_active_chat_id = active_chat_id.strip() if isinstance(active_chat_id, str) else ""
    chat_ids = {chat.id for chat in chats if isinstance(chat.id, str) and chat.id.strip()}
    if normalized_active_chat_id and normalized_active_chat_id in chat_ids:
        return normalized_active_chat_id
    if chats:
        return chats[0].id
    return ""


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
            "theme": _normalize_theme_mode(settings.theme),
        }
    )


def _normalize_theme_mode(raw_theme: object) -> Literal["light", "dark", "business"]:
    value = str(raw_theme).strip().lower()
    if value == "dark":
        return "dark"
    if value == "business":
        return "business"
    return "light"


def _deserialize_provider_id_list(raw_value: object) -> list[str]:
    if isinstance(raw_value, list):
        return sorted({str(entry).strip() for entry in raw_value if str(entry).strip()})
    text = str(raw_value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [entry.strip() for entry in text.split(",") if entry.strip()]
    if not isinstance(parsed, list):
        return []
    return sorted({str(entry).strip() for entry in parsed if str(entry).strip()})


def _serialize_provider_id_list(provider_ids: list[str]) -> str:
    normalized = sorted({str(entry).strip() for entry in provider_ids if str(entry).strip()})
    return json.dumps(normalized)


def _normalize_timezone_name(raw_timezone: object) -> str:
    value = str(raw_timezone).strip()
    if not value:
        return ""
    if value.upper() == "UTC":
        return "UTC"
    return value


def _resolve_timezone(raw_timezone: object, raw_offset_minutes: object = 0) -> tuple[str, tzinfo]:
    timezone_name = _normalize_timezone_name(raw_timezone)
    if not timezone_name:
        now_local = datetime.now().astimezone()
        tz = now_local.tzinfo
        zone_key = getattr(tz, "key", "")
        if isinstance(zone_key, str) and zone_key.strip():
            try:
                return zone_key.strip(), ZoneInfo(zone_key.strip())
            except ZoneInfoNotFoundError:
                pass
        offset = now_local.utcoffset() or timedelta(minutes=0)
        offset_minutes = int(offset.total_seconds() // 60)
        safe_offset = max(-840, min(840, offset_minutes))
        if safe_offset == 0:
            return "UTC", timezone.utc
        sign = "+" if safe_offset >= 0 else "-"
        abs_minutes = abs(safe_offset)
        hours = abs_minutes // 60
        minutes = abs_minutes % 60
        return f"UTC{sign}{hours:02d}:{minutes:02d}", timezone(timedelta(minutes=safe_offset))

    if timezone_name == "UTC":
        return "UTC", timezone.utc
    try:
        return timezone_name, ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        pass

    try:
        offset_minutes = int(str(raw_offset_minutes).strip() or "0")
    except (TypeError, ValueError):
        offset_minutes = 0
    safe_offset = max(-840, min(840, offset_minutes))
    if safe_offset == 0:
        return "UTC", timezone.utc
    sign = "+" if safe_offset >= 0 else "-"
    abs_minutes = abs(safe_offset)
    hours = abs_minutes // 60
    minutes = abs_minutes % 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}", timezone(timedelta(minutes=safe_offset))


def _server_timezone() -> tuple[str, tzinfo]:
    now_local = datetime.now().astimezone()
    tz = now_local.tzinfo
    zone_key = getattr(tz, "key", "") if tz is not None else ""
    if isinstance(zone_key, str) and zone_key.strip():
        try:
            return zone_key.strip(), ZoneInfo(zone_key.strip())
        except ZoneInfoNotFoundError:
            pass
    offset = now_local.utcoffset() or timedelta(minutes=0)
    safe_offset = max(-840, min(840, int(offset.total_seconds() // 60)))
    if safe_offset == 0:
        return "UTC", timezone.utc
    sign = "+" if safe_offset >= 0 else "-"
    abs_minutes = abs(safe_offset)
    hours = abs_minutes // 60
    minutes = abs_minutes % 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}", timezone(timedelta(minutes=safe_offset))


def _normalize_interval(raw_interval: object) -> TimedJobInterval:
    value = str(raw_interval).strip().lower()
    if value == "hourly":
        return "hourly"
    if value == "every_2_hours":
        return "every_2_hours"
    if value == "every_30_min":
        return "every_30_min"
    if value == "every_15_min":
        return "every_15_min"
    if value == "every_10_min":
        return "every_10_min"
    if value == "every_5_min":
        return "every_5_min"
    if value == "weekly":
        return "weekly"
    if value == "monthly":
        return "monthly"
    if value == "once":
        return "once"
    return "daily"


def _parse_start_date(raw_date: object) -> date:
    value = str(raw_date).strip()
    if not value:
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc).date()


def _parse_time_of_day(raw_time: object) -> time:
    value = str(raw_time).strip()
    if not value:
        return time(hour=0, minute=0)
    try:
        parsed = time.fromisoformat(value)
        return time(hour=parsed.hour, minute=parsed.minute)
    except ValueError:
        return time(hour=0, minute=0)


def _normalize_channels(raw_channels: object) -> list[str]:
    if not isinstance(raw_channels, list):
        return ["gateway"]
    unique: list[str] = []
    for entry in raw_channels:
        channel_id = str(entry).strip().lower()
        if not channel_id:
            continue
        if channel_id in unique:
            continue
        unique.append(channel_id)
    return unique if unique else ["gateway"]


def _make_local_datetime(local_date: date, local_time: time, tz: tzinfo) -> datetime:
    return datetime(
        local_date.year,
        local_date.month,
        local_date.day,
        local_time.hour,
        local_time.minute,
        tzinfo=tz,
    )


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _month_candidate(year: int, month: int, desired_day: int, local_time: time, tz: tzinfo) -> datetime:
    last_day = monthrange(year, month)[1]
    day = min(desired_day, last_day)
    return datetime(year, month, day, local_time.hour, local_time.minute, tzinfo=tz)


def _calculate_next_run_at(
    *,
    interval: TimedJobInterval,
    start_date_value: date,
    time_value: time,
    now_utc: datetime,
    last_run_at: str = "",
) -> str:
    _, tz = _server_timezone()
    now_local = now_utc.astimezone(tz)
    base_local = _make_local_datetime(start_date_value, time_value, tz)

    if interval == "once":
        if last_run_at.strip():
            return ""
        if base_local <= now_local:
            return now_utc.isoformat()
        return base_local.astimezone(timezone.utc).isoformat()

    if interval == "daily":
        candidate = _make_local_datetime(now_local.date(), time_value, tz)
        if candidate < base_local:
            candidate = base_local
        if candidate <= now_local:
            candidate = candidate.replace(second=0, microsecond=0) + timedelta(days=1)
        return candidate.astimezone(timezone.utc).isoformat()

    if interval in {"hourly", "every_2_hours", "every_30_min", "every_15_min", "every_10_min", "every_5_min"}:
        cadence_minutes = {
            "hourly": 60,
            "every_2_hours": 120,
            "every_30_min": 30,
            "every_15_min": 15,
            "every_10_min": 10,
            "every_5_min": 5,
        }[interval]
        cadence = timedelta(minutes=cadence_minutes)
        candidate = base_local
        if candidate <= now_local:
            elapsed_seconds = (now_local - candidate).total_seconds()
            elapsed_intervals = int(elapsed_seconds // cadence.total_seconds()) + 1
            candidate = candidate + (cadence * elapsed_intervals)
        return candidate.astimezone(timezone.utc).isoformat()

    if interval == "weekly":
        target_weekday = base_local.weekday()
        days_ahead = (target_weekday - now_local.weekday()) % 7
        candidate_date = now_local.date() + timedelta(days=days_ahead)
        candidate = _make_local_datetime(candidate_date, time_value, tz)
        if candidate < base_local:
            candidate = base_local
        if candidate <= now_local:
            candidate += timedelta(days=7)
        return candidate.astimezone(timezone.utc).isoformat()

    desired_day = base_local.day
    candidate = _month_candidate(now_local.year, now_local.month, desired_day, time_value, tz)
    if candidate < base_local:
        candidate = base_local
    while candidate <= now_local:
        year, month = _next_month(candidate.year, candidate.month)
        candidate = _month_candidate(year, month, desired_day, time_value, tz)
    return candidate.astimezone(timezone.utc).isoformat()


def _decode_channels_json(raw_value: object) -> list[str]:
    try:
        payload = json.loads(str(raw_value or "[]"))
    except json.JSONDecodeError:
        payload = []
    return _normalize_channels(payload)


def _row_to_timed_job(row: sqlite3.Row) -> TimedJob:
    stored_tz_name = str(row["timezone"]).strip()
    if stored_tz_name:
        # Use the timezone that was persisted when the job was created/updated.
        timezone_name = stored_tz_name
        timezone_offset_minutes = max(-840, min(840, int(row["timezone_offset_minutes"] or 0)))
    else:
        # Legacy row created before the timezone columns were populated — fall back to the
        # current server timezone so the job still has a valid timezone value.
        _tz_name, _tz = _server_timezone()
        _offset = _tz.utcoffset(datetime.now(timezone.utc).astimezone(_tz)) or timedelta(minutes=0)
        timezone_name = _tz_name
        timezone_offset_minutes = max(-840, min(840, int(_offset.total_seconds() // 60)))
    return TimedJob(
        id=str(row["id"]),
        title=str(row["title"]),
        prompt=str(row["prompt"]),
        interval=_normalize_interval(row["interval_type"]),
        start_date=str(row["start_date"]),
        time_of_day=str(row["time_of_day"]),
        timezone=timezone_name,
        timezone_offset_minutes=timezone_offset_minutes,
        enabled=bool(row["enabled"]),
        output_decision_enabled=bool(row["output_decision_enabled"]),
        channels=_decode_channels_json(row["channels_json"]),
        provider_id=str(row["provider_id"]),
        model=str(row["model"]),
        next_run_at=str(row["next_run_at"]),
        last_run_at=str(row["last_run_at"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _timed_job_sort_key(job: TimedJob) -> tuple[int, str, str]:
    if job.enabled and job.next_run_at.strip():
        return (0, job.next_run_at, job.title.lower())
    return (1, job.updated_at, job.title.lower())


async def list_timed_jobs() -> list[TimedJob]:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_list_timed_jobs_sync)


async def get_timed_job(timed_job_id: str) -> TimedJob | None:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_get_timed_job_sync, timed_job_id)


def _list_timed_jobs_sync() -> list[TimedJob]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        rows = conn.execute("SELECT * FROM timed_jobs ORDER BY id ASC").fetchall()
        jobs = [_row_to_timed_job(row) for row in rows]
        jobs.sort(key=_timed_job_sort_key)
        return jobs
    finally:
        conn.close()


def _get_timed_job_sync(timed_job_id: str) -> TimedJob | None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute("SELECT * FROM timed_jobs WHERE id = ?", (timed_job_id.strip(),)).fetchone()
        if row is None:
            return None
        return _row_to_timed_job(row)
    finally:
        conn.close()


def _sanitize_timed_job_payload(payload: dict[str, object], existing_id: str = "") -> TimedJob:
    now_utc = datetime.now(timezone.utc)
    timezone_name, tz = _server_timezone()
    offset = tz.utcoffset(now_utc.astimezone(tz)) or timedelta(minutes=0)
    timezone_offset_minutes = int(offset.total_seconds() // 60)
    interval = _normalize_interval(payload.get("interval", "daily"))
    start_date_value = _parse_start_date(payload.get("start_date", ""))
    time_value = _parse_time_of_day(payload.get("time_of_day", ""))
    enabled = bool(payload.get("enabled", False))
    output_decision_enabled = bool(payload.get("output_decision_enabled", False))
    channels = _normalize_channels(payload.get("channels", ["gateway"]))
    provider_id = str(payload.get("provider_id", "")).strip()
    model = str(payload.get("model", "")).strip()
    prompt = str(payload.get("prompt", "")).strip()
    title = " ".join(str(payload.get("title", "")).split()).strip()
    job_id = existing_id.strip() if existing_id.strip() else str(payload.get("id", "")).strip() or str(uuid.uuid4())
    last_run_at = str(payload.get("last_run_at", "")).strip()
    created_at = str(payload.get("created_at", "")).strip() or now_utc.isoformat()
    updated_at = now_utc.isoformat()

    safe_title = title[:120].strip()
    safe_prompt = prompt[:5000].strip()
    safe_provider_id = provider_id[:120].strip().lower()
    safe_model = model[:200].strip()
    if not safe_provider_id:
        safe_model = ""
    safe_start_date = start_date_value.isoformat()
    safe_time_of_day = f"{time_value.hour:02d}:{time_value.minute:02d}"

    if enabled:
        next_run_at = _calculate_next_run_at(
            interval=interval,
            start_date_value=start_date_value,
            time_value=time_value,
            now_utc=now_utc,
            last_run_at=last_run_at,
        )
        if interval == "once" and not next_run_at:
            enabled = False
    else:
        next_run_at = ""

    return TimedJob(
        id=job_id,
        title=safe_title,
        prompt=safe_prompt,
        interval=interval,
        start_date=safe_start_date,
        time_of_day=safe_time_of_day,
        timezone=timezone_name,
        timezone_offset_minutes=timezone_offset_minutes,
        enabled=enabled,
        output_decision_enabled=output_decision_enabled,
        channels=channels,
        provider_id=safe_provider_id,
        model=safe_model,
        next_run_at=next_run_at,
        last_run_at=last_run_at,
        created_at=created_at,
        updated_at=updated_at,
    )


async def upsert_timed_job(payload: dict[str, object], *, timed_job_id: str = "") -> TimedJob:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_upsert_timed_job_sync, payload, timed_job_id)


def _upsert_timed_job_sync(payload: dict[str, object], timed_job_id: str) -> TimedJob:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        existing_id = timed_job_id.strip() or str(payload.get("id", "")).strip()
        existing_row = None
        rearm_existing_once_job = False
        if existing_id:
            existing_row = conn.execute("SELECT * FROM timed_jobs WHERE id = ?", (existing_id,)).fetchone()

        merged_payload = dict(payload)
        if existing_row is not None:
            merged_payload.setdefault("created_at", str(existing_row["created_at"]))
            merged_payload.setdefault("last_run_at", str(existing_row["last_run_at"]))
            merged_payload.setdefault("output_decision_enabled", bool(existing_row["output_decision_enabled"]))
            merged_payload.setdefault("provider_id", str(existing_row["provider_id"]))
            merged_payload.setdefault("model", str(existing_row["model"]))
            merged_payload["id"] = str(existing_row["id"])

            requested_interval = _normalize_interval(merged_payload.get("interval", existing_row["interval_type"]))
            requested_enabled = bool(merged_payload.get("enabled", bool(existing_row["enabled"])))
            if requested_interval == "once" and requested_enabled:
                rearm_existing_once_job = True
                merged_payload["last_run_at"] = ""

        job = _sanitize_timed_job_payload(merged_payload, existing_id=existing_id)
        if rearm_existing_once_job and job.enabled:
            next_run_dt = _parse_utc_iso(job.next_run_at)
            min_rearm_run_at = (datetime.now(timezone.utc) + timedelta(minutes=1)).replace(second=0, microsecond=0)
            if next_run_dt is None or next_run_dt < min_rearm_run_at:
                job = job.model_copy(update={"next_run_at": min_rearm_run_at.isoformat()})

        conn.execute(
            """
            INSERT INTO timed_jobs (
              id, title, prompt, interval_type, start_date, time_of_day, timezone,
              timezone_offset_minutes, enabled, output_decision_enabled, channels_json, provider_id, model, next_run_at, last_run_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title = excluded.title,
              prompt = excluded.prompt,
              interval_type = excluded.interval_type,
              start_date = excluded.start_date,
              time_of_day = excluded.time_of_day,
              timezone = excluded.timezone,
              timezone_offset_minutes = excluded.timezone_offset_minutes,
              enabled = excluded.enabled,
              output_decision_enabled = excluded.output_decision_enabled,
              channels_json = excluded.channels_json,
              provider_id = excluded.provider_id,
              model = excluded.model,
              next_run_at = excluded.next_run_at,
              last_run_at = excluded.last_run_at,
              created_at = excluded.created_at,
              updated_at = excluded.updated_at
            """,
            (
                job.id,
                job.title,
                job.prompt,
                job.interval,
                job.start_date,
                job.time_of_day,
                job.timezone,
                job.timezone_offset_minutes,
                int(job.enabled),
                int(job.output_decision_enabled),
                json.dumps(job.channels),
                job.provider_id,
                job.model,
                job.next_run_at,
                job.last_run_at,
                job.created_at,
                job.updated_at,
            ),
        )
        conn.commit()
        return job
    finally:
        conn.close()


async def delete_timed_job(timed_job_id: str) -> bool:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_delete_timed_job_sync, timed_job_id)


def _delete_timed_job_sync(timed_job_id: str) -> bool:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        cursor = conn.execute("DELETE FROM timed_jobs WHERE id = ?", (timed_job_id.strip(),))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


async def list_due_timed_jobs(*, now_utc: datetime | None = None, limit: int = 25) -> list[TimedJob]:
    await ensure_settings_file()
    safe_now = now_utc or datetime.now(timezone.utc)
    safe_limit = max(1, min(100, int(limit)))
    async with _DB_LOCK:
        return await asyncio.to_thread(_list_due_timed_jobs_sync, safe_now, safe_limit)


def _list_due_timed_jobs_sync(now_utc: datetime, limit: int) -> list[TimedJob]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        rows = conn.execute(
            """
            SELECT *
            FROM timed_jobs
            WHERE enabled = 1
              AND next_run_at != ''
            ORDER BY next_run_at ASC
            """
        ).fetchall()

        due: list[TimedJob] = []
        for row in rows:
            should_run = False
            next_run_raw = str(row["next_run_at"]).strip()
            if next_run_raw:
                try:
                    next_run = datetime.fromisoformat(next_run_raw)
                    if next_run.tzinfo is None:
                        next_run = next_run.replace(tzinfo=timezone.utc)
                    if next_run <= now_utc:
                        should_run = True
                except ValueError:
                    should_run = False

            interval_type = _normalize_interval(row["interval_type"])
            if not should_run and interval_type == "once":
                last_run_at = str(row["last_run_at"]).strip()
                if not last_run_at:
                    start_date_value = _parse_start_date(row["start_date"])
                    time_value = _parse_time_of_day(row["time_of_day"])
                    _, tz = _server_timezone()
                    candidate = _make_local_datetime(start_date_value, time_value, tz).astimezone(timezone.utc)
                    if candidate <= now_utc:
                        should_run = True

            if should_run:
                due.append(_row_to_timed_job(row))
            if len(due) >= limit:
                break
        return due
    finally:
        conn.close()


async def mark_timed_job_executed(timed_job_id: str, *, executed_at_utc: datetime | None = None) -> TimedJob | None:
    await ensure_settings_file()
    safe_time = executed_at_utc or datetime.now(timezone.utc)
    async with _DB_LOCK:
        return await asyncio.to_thread(_mark_timed_job_executed_sync, timed_job_id, safe_time)


def _mark_timed_job_executed_sync(timed_job_id: str, executed_at_utc: datetime) -> TimedJob | None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute("SELECT * FROM timed_jobs WHERE id = ?", (timed_job_id.strip(),)).fetchone()
        if row is None:
            return None

        job = _row_to_timed_job(row)
        if not job.enabled:
            return job

        start_date_value = _parse_start_date(job.start_date)
        time_value = _parse_time_of_day(job.time_of_day)
        next_run_at = ""
        enabled = job.enabled
        if job.interval == "once":
            enabled = False
        else:
            next_run_at = _calculate_next_run_at(
                interval=job.interval,
                start_date_value=start_date_value,
                time_value=time_value,
                now_utc=executed_at_utc,
                last_run_at=executed_at_utc.isoformat(),
            )

        updated_at = executed_at_utc.isoformat()
        conn.execute(
            """
            UPDATE timed_jobs
            SET enabled = ?,
                next_run_at = ?,
                last_run_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                int(enabled),
                next_run_at,
                executed_at_utc.isoformat(),
                updated_at,
                job.id,
            ),
        )
        conn.commit()
        return job.model_copy(
            update={
                "enabled": enabled,
                "next_run_at": next_run_at,
                "last_run_at": executed_at_utc.isoformat(),
                "updated_at": updated_at,
            }
        )
    finally:
        conn.close()


async def list_scripts() -> list[ScriptDefinition]:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_list_scripts_sync)


async def get_script(script_id: str) -> ScriptDefinition | None:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_get_script_sync, script_id)


async def upsert_script(payload: dict[str, object], *, script_id: str = "") -> ScriptDefinition:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_upsert_script_sync, payload, script_id)


async def delete_script(script_id: str) -> bool:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_delete_script_sync, script_id)


async def rehydrate_script_files() -> dict[str, int]:
    await ensure_settings_file()
    async with _DB_LOCK:
        scripts = await asyncio.to_thread(_list_scripts_sync)
    written = await asyncio.to_thread(_write_script_files_sync, scripts)
    return {
        "scripts_count": len(scripts),
        "files_written": written,
    }


def _list_scripts_sync() -> list[ScriptDefinition]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        rows = conn.execute("SELECT * FROM scripts ORDER BY title ASC").fetchall()
        return [_row_to_script(row) for row in rows]
    finally:
        conn.close()


def _get_script_sync(script_id: str) -> ScriptDefinition | None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute("SELECT * FROM scripts WHERE id = ?", (script_id.strip(),)).fetchone()
        if row is None:
            return None
        return _row_to_script(row)
    finally:
        conn.close()


def _upsert_script_sync(payload: dict[str, object], script_id: str) -> ScriptDefinition:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        existing_id = script_id.strip() or str(payload.get("id", "")).strip()
        existing_row = None
        if existing_id:
            existing_row = conn.execute("SELECT * FROM scripts WHERE id = ?", (existing_id,)).fetchone()

        now_iso = datetime.now(timezone.utc).isoformat()
        safe_id = existing_id or str(payload.get("title", "")).strip()
        safe_title = str(payload.get("title", "")).strip()[:64]
        safe_description = str(payload.get("description", "")).strip()[:1024]
        safe_instructions = str(payload.get("instructions", "")).strip()[:5000]
        safe_python_requirements = str(
            payload.get("python_requirements", payload.get("requirements", ""))
        ).strip()[:500]
        safe_body = str(payload.get("body", ""))
        safe_file_name = str(payload.get("file_name", "")).strip()[:100]
        safe_created_at = (
            str(payload.get("created_at", "")).strip()
            or (str(existing_row["created_at"]) if existing_row is not None else "")
            or now_iso
        )

        script = ScriptDefinition(
            id=safe_id,
            title=safe_title,
            description=safe_description,
            instructions=safe_instructions,
            python_requirements=safe_python_requirements,
            body=safe_body,
            file_name=safe_file_name,
            created_at=safe_created_at,
            updated_at=now_iso,
        )

        conn.execute(
            """
            INSERT INTO scripts (
              id, title, description, instructions, requirements, python_requirements, body, file_name, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title = excluded.title,
              description = excluded.description,
              instructions = excluded.instructions,
              requirements = excluded.requirements,
              python_requirements = excluded.python_requirements,
              body = excluded.body,
              file_name = excluded.file_name,
              created_at = excluded.created_at,
              updated_at = excluded.updated_at
            """,
            (
                script.id,
                script.title,
                script.description,
                script.instructions,
                "",
                script.python_requirements,
                script.body,
                script.file_name,
                script.created_at,
                script.updated_at,
            ),
        )
        conn.commit()
        return script
    finally:
        conn.close()


def _delete_script_sync(script_id: str) -> bool:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        cursor = conn.execute("DELETE FROM scripts WHERE id = ?", (script_id.strip(),))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def _row_to_script(row: sqlite3.Row) -> ScriptDefinition:
    return ScriptDefinition(
        id=str(row["id"]),
        title=str(row["title"]),
        description=str(row["description"]),
        instructions=str(row["instructions"]),
        python_requirements=str(row["python_requirements"] or row["requirements"]),
        body=str(row["body"]),
        file_name=str(row["file_name"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _render_script_file_content(script: ScriptDefinition) -> str:
    title = " ".join(str(script.title).split()).strip()
    description = " ".join(str(script.description).split()).strip()
    instructions = " ".join(str(script.instructions).split()).strip()
    python_requirements = " ".join(str(script.python_requirements).split()).strip()
    lines = [
        f"# krill-script-title: {title}",
        f"# krill-script-description: {description}",
        f"# krill-script-instructions: {instructions}",
        f"# krill-script-python-requirements: {python_requirements}",
        "",
    ]
    body = script.body.rstrip("\n")
    if body:
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def _write_script_files_sync(scripts: list[ScriptDefinition]) -> int:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for script in scripts:
        file_name = str(script.file_name or "").strip()
        if not file_name:
            continue
        path = (SCRIPTS_DIR / file_name).resolve()
        if path.parent != SCRIPTS_DIR:
            continue
        rendered = _render_script_file_content(script)
        if path.exists() and path.is_file():
            try:
                existing = path.read_text(encoding="utf-8")
            except Exception:
                existing = ""
            if existing == rendered:
                continue
        path.write_text(rendered, encoding="utf-8")
        written += 1
    return written


async def create_braindump_snapshot(target_path: Path) -> None:
    """Creates a consistent SQLite backup of the current state."""
    await ensure_settings_file()
    async with _DB_LOCK:
        src = await asyncio.to_thread(_get_conn, BRAINDUMP_PATH)
        dst = await asyncio.to_thread(_get_conn, target_path)
        try:
            await asyncio.to_thread(src.backup, dst)
            await asyncio.to_thread(dst.execute, "PRAGMA journal_mode = DELETE")
            await asyncio.to_thread(dst.execute, "VACUUM")
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_memory_text(text: str) -> str:
    return " ".join(str(text).split()).strip()


def _fuzzy_memory_exists(candidate: str, existing_set: set[str]) -> bool:
    """Check if *candidate* is a near-duplicate of any entry in *existing_set*.

    Catches substring containment and normalized-token overlap so that
    ``"The user likes short answers"`` matches
    ``"The user likes short, concise answers."`` without requiring an exact hit.
    """
    low = candidate.lower().strip()
    if not low:
        return False
    # Exact match is already handled by the caller; check fuzzy cases.
    tokens_candidate = set(re.findall(r"[a-z0-9]+", low))
    if len(tokens_candidate) < 3:
        # Very short candidates: only match on substring containment.
        for existing in existing_set:
            if low in existing or existing in low:
                return True
        return False
    for existing in existing_set:
        if low in existing or existing in low:
            return True
        tokens_existing = set(re.findall(r"[a-z0-9]+", existing))
        if not tokens_existing:
            continue
        overlap = tokens_candidate & tokens_existing
        # If >= 80% of the smaller set overlaps with the larger, consider it a match.
        smaller = min(len(tokens_candidate), len(tokens_existing))
        if smaller > 0 and len(overlap) / smaller >= 0.80:
            return True
    return False


async def register_user_message_event() -> tuple[int, int, bool]:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_register_user_message_event_sync)


def _register_user_message_event_sync() -> tuple[int, int, bool]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute(
            "SELECT user_message_count, memory_extraction_interval FROM settings_core WHERE id = 1"
        ).fetchone()
        if row is None:
            conn.execute("INSERT OR IGNORE INTO settings_core (id) VALUES (1)")
            row = conn.execute(
                "SELECT user_message_count, memory_extraction_interval FROM settings_core WHERE id = 1"
            ).fetchone()
        current_count = int(row["user_message_count"] if row else 0)
        interval = int(row["memory_extraction_interval"] if row else 10)
        safe_interval = max(1, interval)
        next_count = max(0, current_count) + 1
        conn.execute("UPDATE settings_core SET user_message_count = ? WHERE id = 1", (next_count,))
        conn.commit()
        return next_count, safe_interval, next_count % safe_interval == 0
    finally:
        conn.close()


async def append_conversation_turn(
    *,
    source_channel: str,
    source_chat_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    await ensure_settings_file()
    async with _DB_LOCK:
        await asyncio.to_thread(
            _append_conversation_turn_sync,
            source_channel,
            source_chat_id,
            user_message,
            assistant_message,
        )


def _append_conversation_turn_sync(
    source_channel: str,
    source_chat_id: str,
    user_message: str,
    assistant_message: str,
) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        conn.execute(
            """
            INSERT INTO conversation_turns (source_channel, source_chat_id, user_message, assistant_message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(source_channel).strip(),
                str(source_chat_id).strip(),
                str(user_message),
                str(assistant_message),
                _utc_now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


async def get_recent_conversation_turns(limit: int) -> list[dict[str, str]]:
    await ensure_settings_file()
    safe_limit = max(1, min(500, int(limit)))
    async with _DB_LOCK:
        return await asyncio.to_thread(_get_recent_conversation_turns_sync, safe_limit)


def _get_recent_conversation_turns_sync(limit: int) -> list[dict[str, str]]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        rows = conn.execute(
            """
            SELECT source_channel, source_chat_id, user_message, assistant_message, created_at
            FROM conversation_turns
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "source_channel": str(row["source_channel"]),
                    "source_chat_id": str(row["source_chat_id"]),
                    "user_message": str(row["user_message"]),
                    "assistant_message": str(row["assistant_message"]),
                    "created_at": str(row["created_at"]),
                }
            )
        result.reverse()
        return result
    finally:
        conn.close()


async def get_last_daily_summary_date() -> str:
    """Return the date string (YYYY-MM-DD) of the last daily summary extraction, or empty string."""
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_get_last_daily_summary_date_sync)


def _get_last_daily_summary_date_sync() -> str:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute("SELECT last_daily_summary_date FROM settings_core WHERE id = 1").fetchone()
        if row is None:
            return ""
        return str(row["last_daily_summary_date"]).strip()
    finally:
        conn.close()


async def set_last_daily_summary_date(date_str: str) -> None:
    """Persist the date string (YYYY-MM-DD) of the last daily summary extraction."""
    await ensure_settings_file()
    async with _DB_LOCK:
        await asyncio.to_thread(_set_last_daily_summary_date_sync, date_str)


def _set_last_daily_summary_date_sync(date_str: str) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        conn.execute(
            "UPDATE settings_core SET last_daily_summary_date = ? WHERE id = 1",
            (str(date_str).strip(),),
        )
        conn.commit()
    finally:
        conn.close()


async def get_conversation_turns_for_date(target_date: str, source_channel: str = "") -> list[dict[str, str]]:
    """Return conversation turns for a specific date (YYYY-MM-DD), optionally filtered by source_channel."""
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_get_conversation_turns_for_date_sync, target_date, source_channel)


def _get_conversation_turns_for_date_sync(target_date: str, source_channel: str) -> list[dict[str, str]]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        if source_channel:
            rows = conn.execute(
                """
                SELECT source_channel, source_chat_id, user_message, assistant_message, created_at
                FROM conversation_turns
                WHERE created_at LIKE ? AND source_channel = ?
                ORDER BY id ASC
                """,
                (f"{target_date}%", source_channel),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT source_channel, source_chat_id, user_message, assistant_message, created_at
                FROM conversation_turns
                WHERE created_at LIKE ?
                ORDER BY id ASC
                """,
                (f"{target_date}%",),
            ).fetchall()
        return [
            {
                "source_channel": str(row["source_channel"]),
                "source_chat_id": str(row["source_chat_id"]),
                "user_message": str(row["user_message"]),
                "assistant_message": str(row["assistant_message"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


async def list_short_term_memories(status: str = "pending") -> list[ShortTermMemoryItem]:
    await ensure_settings_file()
    target_status = status if status in {"pending", "accepted", "rejected"} else "pending"
    async with _DB_LOCK:
        return await asyncio.to_thread(_list_short_term_memories_sync, target_status)


def _list_short_term_memories_sync(status: str) -> list[ShortTermMemoryItem]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        rows = conn.execute(
            """
            SELECT id, content, memory_type, source_channel, source_chat_id, source_request_id, status, created_at
            FROM short_term_memories
            WHERE status = ?
            ORDER BY id ASC
            """,
            (status,),
        ).fetchall()
        result: list[ShortTermMemoryItem] = []
        for row in rows:
            memory_type_raw = str(row["memory_type"])
            memory_type: Literal["core", "normal"] = "core" if memory_type_raw == "core" else "normal"
            status_raw = str(row["status"])
            if status_raw == "accepted":
                status_value: Literal["pending", "accepted", "rejected"] = "accepted"
            elif status_raw == "rejected":
                status_value = "rejected"
            else:
                status_value = "pending"

            result.append(
                ShortTermMemoryItem(
                    id=int(row["id"]),
                    content=str(row["content"]),
                    memory_type=memory_type,
                    source_channel=str(row["source_channel"]),
                    source_chat_id=str(row["source_chat_id"]),
                    source_request_id=str(row["source_request_id"]),
                    status=status_value,
                    created_at=str(row["created_at"]),
                )
            )
        return result
    finally:
        conn.close()


async def add_short_term_memories(
    *,
    core_memories: list[str],
    normal_memories: list[str],
    core_importance: list[str] | None = None,
    normal_importance: list[str] | None = None,
    source_channel: str,
    source_chat_id: str,
    source_request_id: str,
) -> int:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(
            _add_short_term_memories_sync,
            core_memories,
            normal_memories,
            core_importance,
            normal_importance,
            source_channel,
            source_chat_id,
            source_request_id,
        )


def _add_short_term_memories_sync(
    core_memories: list[str],
    normal_memories: list[str],
    core_importance: list[str] | None,
    normal_importance: list[str] | None,
    source_channel: str,
    source_chat_id: str,
    source_request_id: str,
) -> int:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        pending_rows = conn.execute(
            "SELECT content, memory_type FROM short_term_memories WHERE status = 'pending'"
        ).fetchall()
        pending_keys = {
            (_normalize_memory_text(str(row["content"])).lower(), str(row["memory_type"]))
            for row in pending_rows
            if _normalize_memory_text(str(row["content"]))
        }
        normal_existing_rows = conn.execute("SELECT content FROM memories WHERE memory_type = 'normal'").fetchall()
        existing_normal = {_normalize_memory_text(str(row["content"])) .lower() for row in normal_existing_rows}
        core_existing_rows = conn.execute("SELECT content FROM memories WHERE memory_type = 'core'").fetchall()
        existing_core = {_normalize_memory_text(str(row["content"])) .lower() for row in core_existing_rows}

        safe_core_imp = core_importance if core_importance and len(core_importance) == len(core_memories) else None
        safe_normal_imp = normal_importance if normal_importance and len(normal_importance) == len(normal_memories) else None

        added = 0
        for idx, raw in enumerate(core_memories):
            normalized = _normalize_memory_text(raw)
            if not normalized:
                continue
            importance = safe_core_imp[idx] if safe_core_imp else "medium"
            if importance not in {"high", "medium", "low"}:
                importance = "medium"
            # Drop low-importance core memories entirely
            if importance == "low":
                continue
            key = (normalized.lower(), "core")
            if key in pending_keys:
                continue
            # Also skip if already exists as a permanent core memory (fuzzy)
            if _fuzzy_memory_exists(normalized, existing_core):
                continue
            conn.execute(
                """
                INSERT INTO short_term_memories
                (content, memory_type, source_channel, source_chat_id, source_request_id, status, created_at)
                VALUES (?, 'core', ?, ?, ?, 'pending', ?)
                """,
                (
                    normalized,
                    str(source_channel).strip(),
                    str(source_chat_id).strip(),
                    str(source_request_id).strip(),
                    _utc_now_iso(),
                ),
            )
            pending_keys.add(key)
            added += 1

        for idx, raw in enumerate(normal_memories):
            normalized = _normalize_memory_text(raw)
            if not normalized:
                continue
            importance = safe_normal_imp[idx] if safe_normal_imp else "medium"
            if importance not in {"high", "medium", "low"}:
                importance = "medium"
            # Drop low-importance normal memories entirely
            if importance == "low":
                continue
            lowered = normalized.lower()
            if lowered in existing_normal:
                continue
            # Also check fuzzy duplicate against existing normal memories
            if _fuzzy_memory_exists(normalized, existing_normal):
                continue
            conn.execute(
                "INSERT INTO memories (memory_type, content, created_at) VALUES ('normal', ?, ?)",
                (normalized, _utc_now_iso()),
            )
            existing_normal.add(lowered)
            added += 1

        if added > 0:
            conn.commit()
        return added
    finally:
        conn.close()


async def resolve_short_term_memories(items: list[dict[str, object]]) -> int:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_resolve_short_term_memories_sync, items)


def _resolve_short_term_memories_sync(items: list[dict[str, object]]) -> int:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        core_existing_rows = conn.execute("SELECT content FROM memories WHERE memory_type = 'core'").fetchall()
        normal_existing_rows = conn.execute("SELECT content FROM memories WHERE memory_type = 'normal'").fetchall()
        existing_core = {_normalize_memory_text(str(row["content"])) .lower() for row in core_existing_rows}
        existing_normal = {_normalize_memory_text(str(row["content"])) .lower() for row in normal_existing_rows}

        changed = 0
        for item in items:
            suggestion_id = item.get("id") if isinstance(item, dict) else None
            action = item.get("action") if isinstance(item, dict) else None
            memory_type = item.get("memory_type") if isinstance(item, dict) else None
            if not isinstance(suggestion_id, int) or action not in {"accept", "decline"}:
                continue

            row = conn.execute(
                "SELECT id, content, memory_type FROM short_term_memories WHERE id = ? AND status = 'pending'",
                (suggestion_id,),
            ).fetchone()
            if row is None:
                continue

            target_type = str(memory_type) if memory_type in {"core", "normal"} else str(row["memory_type"])

            if action == "accept":
                content = _normalize_memory_text(str(row["content"]))
                if content:
                    lowered = content.lower()
                    if target_type == "core":
                        if lowered not in existing_core:
                            conn.execute(
                                "INSERT INTO memories (memory_type, content, created_at) VALUES ('core', ?, ?)",
                                (content, _utc_now_iso()),
                            )
                            existing_core.add(lowered)
                    else:
                        if lowered not in existing_normal:
                            conn.execute(
                                "INSERT INTO memories (memory_type, content, created_at) VALUES ('normal', ?, ?)",
                                (content, _utc_now_iso()),
                            )
                            existing_normal.add(lowered)

                conn.execute(
                    "UPDATE short_term_memories SET status = 'accepted', memory_type = ? WHERE id = ?",
                    (target_type, suggestion_id),
                )
                changed += 1
                continue

            conn.execute("UPDATE short_term_memories SET status = 'rejected' WHERE id = ?", (suggestion_id,))
            changed += 1

        if changed > 0:
            conn.commit()
        return changed
    finally:
        conn.close()


async def count_auth_users() -> int:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_count_auth_users_sync)


def _count_auth_users_sync() -> int:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute("SELECT COUNT(*) AS count FROM auth_users WHERE is_active = 1").fetchone()
        return int(row["count"] if row else 0)
    finally:
        conn.close()


async def create_auth_user(username: str, password_hash: str) -> dict[str, str]:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_create_auth_user_sync, username, password_hash)


def _create_auth_user_sync(username: str, password_hash: str) -> dict[str, str]:
    conn = _get_conn(BRAINDUMP_PATH)
    normalized_username = str(username).strip().lower()
    now_iso = _utc_now_iso()
    user_id = str(uuid.uuid4())
    try:
        conn.execute("BEGIN TRANSACTION")
        existing_row = conn.execute("SELECT id FROM auth_users WHERE username = ?", (normalized_username,)).fetchone()
        if existing_row is not None:
            raise ValueError("Username already exists.")
        conn.execute(
            """
            INSERT INTO auth_users (id, username, password_hash, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            """,
            (user_id, normalized_username, password_hash, now_iso, now_iso),
        )
        conn.commit()
        return {"id": user_id, "username": normalized_username, "password_hash": password_hash}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def get_auth_user_by_username(username: str) -> dict[str, str] | None:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_get_auth_user_by_username_sync, username)


def _get_auth_user_by_username_sync(username: str) -> dict[str, str] | None:
    conn = _get_conn(BRAINDUMP_PATH)
    normalized_username = str(username).strip().lower()
    try:
        row = conn.execute(
            "SELECT id, username, password_hash FROM auth_users WHERE username = ? AND is_active = 1",
            (normalized_username,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "username": str(row["username"]),
            "password_hash": str(row["password_hash"]),
        }
    finally:
        conn.close()


async def create_auth_session(
    *,
    session_id: str,
    user_id: str,
    session_hash: str,
    expires_at: str,
    ip: str,
) -> None:
    await ensure_settings_file()
    async with _DB_LOCK:
        await asyncio.to_thread(
            _create_auth_session_sync,
            session_id,
            user_id,
            session_hash,
            expires_at,
            ip,
        )


def _create_auth_session_sync(
    session_id: str,
    user_id: str,
    session_hash: str,
    expires_at: str,
    ip: str,
) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    now_iso = _utc_now_iso()
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            """
            INSERT INTO auth_sessions
            (session_id, user_id, session_hash, created_at, expires_at, last_seen_at, revoked_at, ip)
            VALUES (?, ?, ?, ?, ?, ?, '', ?)
            """,
            (session_id, user_id, session_hash, now_iso, expires_at, now_iso, str(ip).strip()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def get_auth_session_by_id(session_id: str) -> dict[str, str] | None:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_get_auth_session_by_id_sync, session_id)


def _get_auth_session_by_id_sync(session_id: str) -> dict[str, str] | None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute(
            """
            SELECT s.session_id, s.user_id, s.session_hash, s.expires_at, s.revoked_at, u.username
            FROM auth_sessions s
            JOIN auth_users u ON u.id = s.user_id
            WHERE s.session_id = ? AND u.is_active = 1
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "session_id": str(row["session_id"]),
            "user_id": str(row["user_id"]),
            "session_hash": str(row["session_hash"]),
            "expires_at": str(row["expires_at"]),
            "revoked_at": str(row["revoked_at"]),
            "username": str(row["username"]),
        }
    finally:
        conn.close()


async def touch_auth_session(session_id: str) -> None:
    await ensure_settings_file()
    async with _DB_LOCK:
        await asyncio.to_thread(_touch_auth_session_sync, session_id)


def _touch_auth_session_sync(session_id: str) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    now_iso = _utc_now_iso()
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE session_id = ?", (now_iso, session_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def revoke_auth_session(session_id: str) -> None:
    await ensure_settings_file()
    async with _DB_LOCK:
        await asyncio.to_thread(_revoke_auth_session_sync, session_id)


def _revoke_auth_session_sync(session_id: str) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    now_iso = _utc_now_iso()
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE session_id = ? AND revoked_at = ''",
            (now_iso, session_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def revoke_other_auth_sessions(user_id: str, *, except_session_id: str = "") -> int:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_revoke_other_auth_sessions_sync, user_id, except_session_id)


def _revoke_other_auth_sessions_sync(user_id: str, except_session_id: str) -> int:
    conn = _get_conn(BRAINDUMP_PATH)
    now_iso = _utc_now_iso()
    user_id_value = str(user_id).strip()
    except_value = str(except_session_id).strip()
    try:
        conn.execute("BEGIN TRANSACTION")
        if except_value:
            cursor = conn.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE user_id = ? AND session_id != ? AND revoked_at = ''
                """,
                (now_iso, user_id_value, except_value),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE user_id = ? AND revoked_at = ''
                """,
                (now_iso, user_id_value),
            )
        conn.commit()
        return int(cursor.rowcount if cursor.rowcount is not None else 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def update_auth_user_password(user_id: str, password_hash: str) -> None:
    await ensure_settings_file()
    async with _DB_LOCK:
        await asyncio.to_thread(_update_auth_user_password_sync, user_id, password_hash)


def _update_auth_user_password_sync(user_id: str, password_hash: str) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    now_iso = _utc_now_iso()
    try:
        conn.execute("BEGIN TRANSACTION")
        cursor = conn.execute(
            "UPDATE auth_users SET password_hash = ?, updated_at = ? WHERE id = ? AND is_active = 1",
            (str(password_hash), now_iso, str(user_id).strip()),
        )
        if int(cursor.rowcount if cursor.rowcount is not None else 0) <= 0:
            raise ValueError("User account not found.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def clear_auth_ip_lock(ip: str) -> None:
    await ensure_settings_file()
    async with _DB_LOCK:
        await asyncio.to_thread(_clear_auth_ip_lock_sync, ip)


def _clear_auth_ip_lock_sync(ip: str) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM auth_ip_locks WHERE ip = ?", (str(ip).strip(),))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def get_auth_ip_lock(ip: str) -> dict[str, object] | None:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_get_auth_ip_lock_sync, ip)


def _get_auth_ip_lock_sync(ip: str) -> dict[str, object] | None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute(
            "SELECT ip, failed_count, first_failed_at, last_failed_at, banned_until FROM auth_ip_locks WHERE ip = ?",
            (str(ip).strip(),),
        ).fetchone()
        if row is None:
            return None
        return {
            "ip": str(row["ip"]),
            "failed_count": int(row["failed_count"]),
            "first_failed_at": str(row["first_failed_at"]),
            "last_failed_at": str(row["last_failed_at"]),
            "banned_until": str(row["banned_until"]),
        }
    finally:
        conn.close()


async def register_auth_failed_attempt(
    ip: str,
    *,
    failure_window_seconds: int = 3600,
    lockout_threshold: int = 5,
    ban_seconds: int = 3600,
) -> dict[str, object]:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(
            _register_auth_failed_attempt_sync,
            ip,
            failure_window_seconds,
            lockout_threshold,
            ban_seconds,
        )


def _register_auth_failed_attempt_sync(
    ip: str,
    failure_window_seconds: int,
    lockout_threshold: int,
    ban_seconds: int,
) -> dict[str, object]:
    conn = _get_conn(BRAINDUMP_PATH)
    ip_value = str(ip).strip()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    banned_until = ""
    failed_count = 1
    first_failed_at = now_iso
    try:
        row = conn.execute(
            "SELECT failed_count, first_failed_at, banned_until FROM auth_ip_locks WHERE ip = ?",
            (ip_value,),
        ).fetchone()

        if row is not None:
            existing_count = int(row["failed_count"]) if row["failed_count"] is not None else 0
            existing_first = str(row["first_failed_at"] or "")
            existing_ban = str(row["banned_until"] or "")
            existing_ban_dt = _parse_utc_iso(existing_ban)

            if existing_ban_dt is not None and existing_ban_dt > now:
                failed_count = max(1, existing_count)
                first_failed_at = existing_first or now_iso
                banned_until = existing_ban_dt.isoformat()
            else:
                first_dt = _parse_utc_iso(existing_first)
                if first_dt is None or (now - first_dt).total_seconds() > max(1, failure_window_seconds):
                    failed_count = 1
                    first_failed_at = now_iso
                else:
                    failed_count = max(0, existing_count) + 1
                    first_failed_at = first_dt.isoformat()

                if failed_count >= max(1, lockout_threshold):
                    banned_until = (now + timedelta(seconds=max(1, ban_seconds))).isoformat()

        conn.execute("BEGIN TRANSACTION")
        conn.execute(
            """
            INSERT INTO auth_ip_locks (ip, failed_count, first_failed_at, last_failed_at, banned_until)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ip) DO UPDATE SET
              failed_count = excluded.failed_count,
              first_failed_at = excluded.first_failed_at,
              last_failed_at = excluded.last_failed_at,
              banned_until = excluded.banned_until
            """,
            (ip_value, failed_count, first_failed_at, now_iso, banned_until),
        )
        conn.commit()
        return {
            "ip": ip_value,
            "failed_count": failed_count,
            "banned_until": banned_until,
            "is_banned": bool(banned_until),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parse_utc_iso(value: str) -> datetime | None:
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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


def _read_braindump_table_sync(table_name: str, limit: int, offset: int, show_secrets: bool) -> dict[str, object]:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        normalized_table_name = str(table_name or "").strip()
        if not normalized_table_name:
            raise ValueError("Table name is required.")

        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name ASC"
        ).fetchall()
        available_table_names = {str(row["name"]) for row in table_rows}
        if normalized_table_name not in available_table_names:
            raise ValueError(f"Unknown braindump table: {normalized_table_name}")

        safe_limit = max(1, min(int(limit), 500))
        safe_offset = max(0, int(offset))
        quoted = _quote_identifier(normalized_table_name)

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
        result_rows = conn.execute(
            f"SELECT * FROM {quoted} LIMIT ? OFFSET ?",
            (safe_limit, safe_offset),
        ).fetchall()

        rows: list[dict[str, object]] = []
        for raw_row in result_rows:
            entry: dict[str, object] = {}
            for key in raw_row.keys():
                raw_value: Any = raw_row[key]
                if show_secrets or not _is_sensitive_column(str(key)):
                    entry[str(key)] = raw_value
                else:
                    entry[str(key)] = _mask_value(raw_value)
            rows.append(entry)

        return {
            "ok": True,
            "table_name": normalized_table_name,
            "limit": safe_limit,
            "offset": safe_offset,
            "row_count": total_rows,
            "returned_rows": len(rows),
            "columns": columns,
            "rows": rows,
            "show_secrets": show_secrets,
        }
    finally:
        conn.close()


async def read_braindump_table(
    *,
    table_name: str,
    limit: int = 100,
    offset: int = 0,
    show_secrets: bool = False,
) -> dict[str, object]:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(
            _read_braindump_table_sync,
            table_name,
            limit,
            offset,
            show_secrets,
        )


def _load_whatsapp_session_blob_sync() -> str:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        row = conn.execute("SELECT session_blob FROM whatsapp_state WHERE id = 1").fetchone()
        if row is None:
            return ""
        value = row["session_blob"]
        return str(value) if isinstance(value, str) else ""
    finally:
        conn.close()


async def load_whatsapp_session_blob() -> str:
    await ensure_settings_file()
    async with _DB_LOCK:
        return await asyncio.to_thread(_load_whatsapp_session_blob_sync)


def _save_whatsapp_session_blob_sync(blob: str) -> None:
    conn = _get_conn(BRAINDUMP_PATH)
    try:
        conn.execute("BEGIN TRANSACTION")
        conn.execute("INSERT OR IGNORE INTO whatsapp_state (id) VALUES (1)")
        conn.execute("UPDATE whatsapp_state SET session_blob = ? WHERE id = 1", (blob,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def save_whatsapp_session_blob(blob: str) -> None:
    await ensure_settings_file()
    async with _DB_LOCK:
        await asyncio.to_thread(_save_whatsapp_session_blob_sync, blob)
