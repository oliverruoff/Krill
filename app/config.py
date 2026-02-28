"""Settings models and persistence helpers for the shared braindump SQLite database."""

import asyncio
import json
import os
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
    content: str = Field(default="", max_length=1000000)
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
    owner_chat_id: str = ""
    last_update_id: int = Field(default=0, ge=0)


TimedJobInterval = Literal["daily", "weekly", "monthly", "once"]


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
    channels: list[str] = Field(default_factory=list)
    next_run_at: str = ""
    last_run_at: str = ""
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
    tool_max_recursion: int = Field(default=6, ge=1, le=20)
    tool_timeout_seconds: int = Field(default=45, ge=5, le=300)
    memory_extraction_interval: int = Field(default=10, ge=1, le=500)
    user_message_count: int = Field(default=0, ge=0)
    daily_token_usage: list[DailyTokenUsage] = Field(default_factory=list)
    active_chat_id: str = ""
    telegram_state: TelegramState = Field(default_factory=TelegramState)


class ShortTermMemoryItem(BaseModel):
    id: int
    content: str
    memory_type: Literal["core", "normal"]
    source_channel: str = ""
    source_chat_id: str = ""
    source_request_id: str = ""
    status: Literal["pending", "accepted", "rejected"] = "pending"
    created_at: str


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
          tool_max_recursion INTEGER NOT NULL DEFAULT 6,
          tool_timeout_seconds INTEGER NOT NULL DEFAULT 45,
          memory_extraction_interval INTEGER NOT NULL DEFAULT 10,
          user_message_count INTEGER NOT NULL DEFAULT 0
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
          owner_chat_id TEXT NOT NULL DEFAULT '',
          last_update_id INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS whatsapp_state (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          session_blob TEXT NOT NULL DEFAULT ''
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
          interval_type TEXT NOT NULL DEFAULT 'daily' CHECK (interval_type IN ('daily', 'weekly', 'monthly', 'once')),
          start_date TEXT NOT NULL DEFAULT '',
          time_of_day TEXT NOT NULL DEFAULT '00:00',
          timezone TEXT NOT NULL DEFAULT 'UTC',
          timezone_offset_minutes INTEGER NOT NULL DEFAULT 0,
          enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
          channels_json TEXT NOT NULL DEFAULT '[]',
          next_run_at TEXT NOT NULL DEFAULT '',
          last_run_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_timed_jobs_next_run ON timed_jobs(enabled, next_run_at);
    """)

    _ensure_settings_core_column(conn, "memory_extraction_interval", "INTEGER NOT NULL DEFAULT 10")
    _ensure_settings_core_column(conn, "user_message_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_settings_core_column(conn, "user_full_name", "TEXT NOT NULL DEFAULT ''")
    _ensure_settings_core_column(conn, "user_call_name", "TEXT NOT NULL DEFAULT ''")
    _ensure_telegram_state_column(conn, "owner_chat_id", "TEXT NOT NULL DEFAULT ''")
    _ensure_whatsapp_state_column(conn, "session_blob", "TEXT NOT NULL DEFAULT ''")
    _ensure_timed_jobs_column(conn, "timezone_offset_minutes", "INTEGER NOT NULL DEFAULT 0")
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


def _ensure_timed_jobs_column(conn: sqlite3.Connection, column_name: str, definition: str) -> None:
    rows = conn.execute("PRAGMA table_info(timed_jobs)").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE timed_jobs ADD COLUMN {column_name} {definition}")


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
                bot_name = ?, system_prompt = ?, user_full_name = ?, user_call_name = ?, setup_completed = ?, 
                active_provider_id = ?, active_model_id = ?, active_chat_id = ?,
                tool_max_recursion = ?, tool_timeout_seconds = ?,
                memory_extraction_interval = ?
            WHERE id = 1
        """, (
            settings.bot_name, settings.system_prompt, settings.user_full_name, settings.user_call_name, int(settings.setup_completed),
            settings.active_provider_id, settings.active_model_id, settings.active_chat_id,
            settings.tool_max_recursion, settings.tool_timeout_seconds,
            settings.memory_extraction_interval
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


def _normalize_interval(raw_interval: object) -> TimedJobInterval:
    value = str(raw_interval).strip().lower()
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
    allowed = {"gateway", "telegram"}
    unique: list[str] = []
    for entry in raw_channels:
        channel_id = str(entry).strip().lower()
        if channel_id not in allowed:
            continue
        if channel_id in unique:
            continue
        unique.append(channel_id)
    if not unique:
        return ["gateway"]
    return unique


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
    timezone_name: str,
    timezone_offset_minutes: int = 0,
    now_utc: datetime,
    last_run_at: str = "",
) -> str:
    _, tz = _resolve_timezone(timezone_name, timezone_offset_minutes)
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
    timezone_name, _ = _resolve_timezone(row["timezone"], row["timezone_offset_minutes"])
    try:
        timezone_offset_minutes = int(row["timezone_offset_minutes"])
    except (TypeError, ValueError):
        timezone_offset_minutes = 0
    return TimedJob(
        id=str(row["id"]),
        title=str(row["title"]),
        prompt=str(row["prompt"]),
        interval=_normalize_interval(row["interval_type"]),
        start_date=str(row["start_date"]),
        time_of_day=str(row["time_of_day"]),
        timezone=timezone_name,
        timezone_offset_minutes=max(-840, min(840, timezone_offset_minutes)),
        enabled=bool(row["enabled"]),
        channels=_decode_channels_json(row["channels_json"]),
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
    raw_timezone = payload.get("timezone", "UTC")
    raw_timezone_offset_minutes = payload.get("timezone_offset_minutes", 0)
    timezone_name, _ = _resolve_timezone(raw_timezone, raw_timezone_offset_minutes)
    try:
        timezone_offset_minutes = int(str(raw_timezone_offset_minutes).strip() or "0")
    except (TypeError, ValueError):
        timezone_offset_minutes = 0
    timezone_offset_minutes = max(-840, min(840, timezone_offset_minutes))
    interval = _normalize_interval(payload.get("interval", "daily"))
    start_date_value = _parse_start_date(payload.get("start_date", ""))
    time_value = _parse_time_of_day(payload.get("time_of_day", ""))
    enabled = bool(payload.get("enabled", False))
    channels = _normalize_channels(payload.get("channels", ["gateway"]))
    prompt = str(payload.get("prompt", "")).strip()
    title = " ".join(str(payload.get("title", "")).split()).strip()
    job_id = existing_id.strip() if existing_id.strip() else str(payload.get("id", "")).strip() or str(uuid.uuid4())
    last_run_at = str(payload.get("last_run_at", "")).strip()
    created_at = str(payload.get("created_at", "")).strip() or now_utc.isoformat()
    updated_at = now_utc.isoformat()

    safe_title = title[:120].strip()
    safe_prompt = prompt[:5000].strip()
    safe_start_date = start_date_value.isoformat()
    safe_time_of_day = f"{time_value.hour:02d}:{time_value.minute:02d}"

    if enabled:
        next_run_at = _calculate_next_run_at(
            interval=interval,
            start_date_value=start_date_value,
            time_value=time_value,
            timezone_name=timezone_name,
            timezone_offset_minutes=timezone_offset_minutes,
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
        channels=channels,
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
        if existing_id:
            existing_row = conn.execute("SELECT * FROM timed_jobs WHERE id = ?", (existing_id,)).fetchone()

        merged_payload = dict(payload)
        if existing_row is not None:
            merged_payload.setdefault("created_at", str(existing_row["created_at"]))
            merged_payload.setdefault("last_run_at", str(existing_row["last_run_at"]))
            merged_payload["id"] = str(existing_row["id"])

        job = _sanitize_timed_job_payload(merged_payload, existing_id=existing_id)

        conn.execute(
            """
            INSERT INTO timed_jobs (
              id, title, prompt, interval_type, start_date, time_of_day, timezone,
              timezone_offset_minutes, enabled, channels_json, next_run_at, last_run_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title = excluded.title,
              prompt = excluded.prompt,
              interval_type = excluded.interval_type,
              start_date = excluded.start_date,
              time_of_day = excluded.time_of_day,
              timezone = excluded.timezone,
              timezone_offset_minutes = excluded.timezone_offset_minutes,
              enabled = excluded.enabled,
              channels_json = excluded.channels_json,
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
                json.dumps(job.channels),
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
                    _, tz = _resolve_timezone(row["timezone"], row["timezone_offset_minutes"])
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
                timezone_name=_normalize_timezone_name(job.timezone),
                timezone_offset_minutes=job.timezone_offset_minutes,
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
            source_channel,
            source_chat_id,
            source_request_id,
        )


def _add_short_term_memories_sync(
    core_memories: list[str],
    normal_memories: list[str],
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

        added = 0
        for raw in core_memories:
            normalized = _normalize_memory_text(raw)
            if not normalized:
                continue
            key = (normalized.lower(), "core")
            if key in pending_keys:
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

        for raw in normal_memories:
            normalized = _normalize_memory_text(raw)
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in existing_normal:
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
