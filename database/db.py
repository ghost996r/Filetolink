import sqlite3
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from config import DB_PATH, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL, USE_SUPABASE

if USE_SUPABASE:
    try:
        from supabase import Client, create_client
    except ImportError as exc:
        raise RuntimeError("USE_SUPABASE=1 लेकिन supabase package installed nahi hai.") from exc

    _supabase: Client = create_client(SUPABASE_URL or "", SUPABASE_SERVICE_ROLE_KEY or "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(str(DB_PATH), check_same_thread=False)


def init_db() -> None:
    if USE_SUPABASE:
        # Supabase tables SQL editor se create hote hain.
        return

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            join_date TEXT
        )"""
    )

    cur.execute(
        """CREATE TABLE IF NOT EXISTS files (
            file_id TEXT PRIMARY KEY,
            file_path TEXT,
            file_name TEXT,
            user_id INTEGER,
            created_at TEXT,
            expires_at TEXT,
            storage_chat_id INTEGER,
            storage_message_id INTEGER,
            link_token TEXT,
            telegram_file_id TEXT,
            media_title TEXT,
            random_key TEXT
        )"""
    )

    cur.execute(
        """CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            channel_username TEXT,
            added_by INTEGER,
            added_at TEXT
        )"""
    )

    cur.execute(
        """CREATE TABLE IF NOT EXISTS broadcasts (
            message_id INTEGER,
            chat_id INTEGER,
            sent_at TEXT,
            expires_at TEXT
        )"""
    )

    _ensure_file_columns(cur)
    conn.commit()
    conn.close()


def _ensure_file_columns(cur: sqlite3.Cursor) -> None:
    cur.execute("PRAGMA table_info(files)")
    columns = {row[1] for row in cur.fetchall()}
    if "storage_chat_id" not in columns:
        cur.execute("ALTER TABLE files ADD COLUMN storage_chat_id INTEGER")
    if "storage_message_id" not in columns:
        cur.execute("ALTER TABLE files ADD COLUMN storage_message_id INTEGER")
    if "link_token" not in columns:
        cur.execute("ALTER TABLE files ADD COLUMN link_token TEXT")
    if "telegram_file_id" not in columns:
        cur.execute("ALTER TABLE files ADD COLUMN telegram_file_id TEXT")
    if "media_title" not in columns:
        cur.execute("ALTER TABLE files ADD COLUMN media_title TEXT")
    if "random_key" not in columns:
        cur.execute("ALTER TABLE files ADD COLUMN random_key TEXT")


def save_user(user_id: int, username: Optional[str], first_name: Optional[str]) -> None:
    if USE_SUPABASE:
        _supabase.table("users").upsert(
            {
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "join_date": _now_iso(),
            },
            on_conflict="user_id",
        ).execute()
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, join_date) VALUES (?, ?, ?, ?)",
        (user_id, username, first_name, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def list_users() -> List[Tuple[int, Optional[str], Optional[str]]]:
    if USE_SUPABASE:
        resp = _supabase.table("users").select("user_id,username,first_name").execute()
        return [(row["user_id"], row.get("username"), row.get("first_name")) for row in (resp.data or [])]

    conn = get_connection()
    cur = conn.cursor()
    rows = cur.execute("SELECT user_id, username, first_name FROM users").fetchall()
    conn.close()
    return rows


def add_file_record(
    file_id: str,
    file_name: str,
    user_id: int,
    expires_at: str,
    storage_chat_id: Optional[int] = None,
    storage_message_id: Optional[int] = None,
    file_path: Optional[str] = None,
    link_token: Optional[str] = None,
    telegram_file_id: Optional[str] = None,
    media_title: Optional[str] = None,
    random_key: Optional[str] = None,
) -> None:
    if USE_SUPABASE:
        _supabase.table("files").insert(
            {
                "file_id": file_id,
                "file_path": file_path,
                "file_name": file_name,
                "user_id": user_id,
                "created_at": _now_iso(),
                "expires_at": expires_at,
                "storage_chat_id": storage_chat_id,
                "storage_message_id": storage_message_id,
                "link_token": link_token,
                "telegram_file_id": telegram_file_id,
                "media_title": media_title,
                "random_key": random_key,
            }
        ).execute()
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO files (file_id, file_path, file_name, user_id, created_at, expires_at, storage_chat_id, storage_message_id, link_token, telegram_file_id, media_title, random_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            file_id,
            file_path,
            file_name,
            user_id,
            datetime.now().isoformat(),
            expires_at,
            storage_chat_id,
            storage_message_id,
            link_token,
            telegram_file_id,
            media_title,
            random_key,
        ),
    )
    conn.commit()
    conn.close()


def get_active_file(file_id: str) -> Optional[Tuple]:
    if USE_SUPABASE:
        resp = (
            _supabase.table("files")
            .select("file_id,file_path,file_name,user_id,created_at,expires_at,storage_chat_id,storage_message_id")
            .eq("file_id", file_id)
            .gt("expires_at", _now_iso())
            .limit(1)
            .execute()
        )
        if not resp.data:
            return None
        row = resp.data[0]
        return (
            row.get("file_id"),
            row.get("file_path"),
            row.get("file_name"),
            row.get("user_id"),
            row.get("created_at"),
            row.get("expires_at"),
            row.get("storage_chat_id"),
            row.get("storage_message_id"),
        )

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT file_id, file_path, file_name, user_id, created_at, expires_at, storage_chat_id, storage_message_id FROM files WHERE file_id = ? AND expires_at > ?",
        (file_id, datetime.now().isoformat()),
    )
    row = cur.fetchone()
    conn.close()
    return row


def get_expired_files() -> List[Tuple[str, Optional[str], Optional[int], Optional[int]]]:
    if USE_SUPABASE:
        resp = (
            _supabase.table("files")
            .select("file_id,file_path,storage_chat_id,storage_message_id")
            .lt("expires_at", _now_iso())
            .execute()
        )
        return [
            (
                row.get("file_id"),
                row.get("file_path"),
                row.get("storage_chat_id"),
                row.get("storage_message_id"),
            )
            for row in (resp.data or [])
        ]

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT file_id, file_path, storage_chat_id, storage_message_id FROM files WHERE expires_at < ?", (datetime.now().isoformat(),))
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_file_record(file_id: str) -> None:
    if USE_SUPABASE:
        _supabase.table("files").delete().eq("file_id", file_id).execute()
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
    conn.commit()
    conn.close()


def count_users() -> int:
    if USE_SUPABASE:
        resp = _supabase.table("users").select("user_id", count="exact", head=True).execute()
        return int(resp.count or 0)

    conn = get_connection()
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return total


def count_active_files() -> int:
    if USE_SUPABASE:
        resp = (
            _supabase.table("files")
            .select("file_id", count="exact", head=True)
            .gt("expires_at", _now_iso())
            .execute()
        )
        return int(resp.count or 0)

    conn = get_connection()
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM files WHERE expires_at > ?", (datetime.now().isoformat(),)).fetchone()[0]
    conn.close()
    return total


def normalize_channel_username(channel_username: str) -> str:
    username = channel_username.strip()
    if username.startswith("https://t.me/"):
        username = "@" + username.split("https://t.me/", 1)[1].strip("/")
    if not username.startswith("@"):
        username = "@" + username
    return username


def add_channel(channel_username: str, added_by: int, invite_link: str = "") -> str:
    normalized = normalize_channel_username(channel_username)
    if USE_SUPABASE:
        _supabase.table("channels").upsert(
            {
                "channel_id": normalized,
                "channel_username": normalized,
                "invite_link": invite_link,
                "added_by": added_by,
                "added_at": _now_iso(),
            },
            on_conflict="channel_id",
        ).execute()
        return normalized

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO channels (channel_id, channel_username, added_by, added_at) VALUES (?, ?, ?, ?)",
        (normalized, normalized, added_by, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()
    return normalized


def remove_channel(channel_id: str) -> None:
    if USE_SUPABASE:
        _supabase.table("channels").delete().eq("channel_id", channel_id).execute()
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()


def list_channels() -> List[Tuple[str, str, str]]:
    if USE_SUPABASE:
        resp = _supabase.table("channels").select("channel_id,channel_username,invite_link").order("added_at", desc=True).execute()
        return [(row.get("channel_id"), row.get("channel_username"), row.get("invite_link") or "") for row in (resp.data or [])]

    conn = get_connection()
    cur = conn.cursor()
    rows = cur.execute("SELECT channel_id, channel_username FROM channels ORDER BY added_at DESC").fetchall()
    conn.close()
    return [(r[0], r[1], "") for r in rows]


def add_broadcast_record(message_id: int, chat_id: int, expires_at: str) -> None:
    if USE_SUPABASE:
        _supabase.table("broadcasts").insert(
            {
                "message_id": message_id,
                "chat_id": chat_id,
                "sent_at": _now_iso(),
                "expires_at": expires_at,
            }
        ).execute()
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO broadcasts (message_id, chat_id, sent_at, expires_at) VALUES (?, ?, ?, ?)",
        (message_id, chat_id, datetime.now().isoformat(), expires_at),
    )
    conn.commit()
    conn.close()


def get_expired_broadcasts() -> List[Tuple[int, int]]:
    if USE_SUPABASE:
        resp = _supabase.table("broadcasts").select("message_id,chat_id").lt("expires_at", _now_iso()).execute()
        return [(row.get("message_id"), row.get("chat_id")) for row in (resp.data or [])]

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT message_id, chat_id FROM broadcasts WHERE expires_at < ?", (datetime.now().isoformat(),))
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_broadcast_record(message_id: int, chat_id: int) -> None:
    if USE_SUPABASE:
        _supabase.table("broadcasts").delete().eq("message_id", message_id).eq("chat_id", chat_id).execute()
        return

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM broadcasts WHERE message_id = ? AND chat_id = ?", (message_id, chat_id))
    conn.commit()
    conn.close()
