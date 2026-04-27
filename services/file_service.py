from datetime import datetime, timedelta

from telegram.constants import ParseMode

from config import FILE_EXPIRY_MINUTES, LOG_CHANNEL, NEVER_EXPIRE_LINKS, STORAGE_CHANNEL_ID
from database.db import add_file_record as db_add_file_record, get_active_file as db_get_active_file

def build_share_link(bot_username: str, file_id: str) -> str:
    return f"https://t.me/{bot_username}?start={file_id}"


def store_uploaded_file(
    file_id: str,
    file_name: str,
    user_id: int,
    storage_message_id: int,
    storage_chat_id: int = STORAGE_CHANNEL_ID,
    file_path: str | None = None,
    link_token: str | None = None,
    telegram_file_id: str | None = None,
    media_title: str | None = None,
    random_key: str | None = None,
) -> None:
    if NEVER_EXPIRE_LINKS:
        expires_at = "9999-12-31T23:59:59"
    else:
        expires_at = (datetime.now() + timedelta(minutes=FILE_EXPIRY_MINUTES)).isoformat()
    db_add_file_record(
        file_id,
        file_name,
        user_id,
        expires_at,
        storage_chat_id=storage_chat_id,
        storage_message_id=storage_message_id,
        file_path=file_path,
        link_token=link_token,
        telegram_file_id=telegram_file_id,
        media_title=media_title,
        random_key=random_key,
    )


def get_active_file(file_id: str):
    return db_get_active_file(file_id)


async def log_download(context, user_id: int, username: str | None, first_name: str | None, file_name: str) -> None:
    uname = f"@{username}" if username else "unknown"
    log_msg = (
        "👤 <b>New Activity</b>\n\n"
        f"👤 <b>User:</b> {first_name or 'Unknown'} (<code>{uname}</code>)\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"📝 <b>Action:</b> Downloaded: {file_name}\n"
        f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    try:
        await context.bot.send_message(LOG_CHANNEL, log_msg, parse_mode=ParseMode.HTML)
    except Exception:
        pass
