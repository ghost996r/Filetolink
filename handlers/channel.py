from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import ADMIN_ID, REQUIRED_CHANNEL_ENTRIES, REQUIRED_CHANNEL_VERIFY_TARGETS, REQUIRED_CHANNELS
from database.db import add_channel, list_channels, remove_channel
from utils.helpers import ADMIN_STATE, get_target_message, is_admin, normalize_channel_username, parse_quoted_parts

# { user_id -> file_id } - tracks which file user was trying to access
_PENDING_JOIN_ACCESS: dict[int, str] = {}


def _normalize_channel_target(target: str | int | None) -> str | None:
    if target is None:
        return None
    if isinstance(target, int):
        return str(target)
    return target.lstrip("@").lower()


def _chat_matches_target(chat, target: str | int | None) -> bool:
    normalized = _normalize_channel_target(target)
    if normalized is None or chat is None:
        return False

    if isinstance(target, int):
        return chat.id == target

    chat_username = (getattr(chat, "username", None) or "").lstrip("@").lower()
    return chat_username == normalized


async def user_in_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    channels = list_channels()
    for channel_id, _ in channels:
        try:
            member = await context.bot.get_chat_member(channel_id, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception:
            return False
    return True


async def user_in_required_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    if not REQUIRED_CHANNEL_ENTRIES:
        return True

    for _, verify_target in REQUIRED_CHANNEL_ENTRIES:
        if verify_target is None:
            return False

        if user_id in _PENDING_JOIN_ACCESS:
            return True

        try:
            member = await context.bot.get_chat_member(verify_target, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception:
            return False
    return True


def build_join_keyboard(file_id: str) -> InlineKeyboardMarkup:
    keyboard = []
    for _, channel_username in list_channels():
        clean_username = channel_username[1:] if channel_username.startswith("@") else channel_username
        keyboard.append([InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{clean_username}")])
    keyboard.append([InlineKeyboardButton("✅ Joined All?", callback_data=f"check_{file_id}")])
    return InlineKeyboardMarkup(keyboard)


def build_join_keyboard_for_required_channels(file_id: str) -> InlineKeyboardMarkup:
    keyboard = []
    for channel_link in REQUIRED_CHANNELS:
        keyboard.append([InlineKeyboardButton("📢 Join Channel", url=channel_link)])
    keyboard.append([InlineKeyboardButton("✅ Sent Request? Try Again", callback_data=f"check_{file_id}")])
    return InlineKeyboardMarkup(keyboard)


def set_pending_file(user_id: int, file_id: str) -> None:
    _PENDING_JOIN_ACCESS[user_id] = file_id


def get_pending_file(user_id: int) -> str | None:
    return _PENDING_JOIN_ACCESS.pop(user_id, None)


async def channel_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detect join request and deliver pending file WITHOUT approving."""
    join_request = update.chat_join_request
    if not join_request:
        return

    if context.application and context.application.bot_data.get("role") != "secondary":
        return

    user_id = join_request.from_user.id

    for join_target, verify_target in REQUIRED_CHANNEL_ENTRIES:
        if _chat_matches_target(join_request.chat, verify_target):
            file_id = get_pending_file(user_id)
            if file_id:
                from handlers.deliver import send_file_by_id
                await send_file_by_id(update, context, file_id)
            else:
                try:
                    await join_request.from_user.send_message(
                        "✅ Request received! Click your file link again to get the file."
                    )
                except Exception:
                    pass
            return


async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = get_target_message(update)
    if not message or not update.effective_user:
        return

    if not is_admin(update.effective_user.id, ADMIN_ID):
        return

    if not context.args:
        await message.reply_text("Usage: /addchannel @channelusername")
        return

    channel_username = normalize_channel_username(context.args[0])
    add_channel(channel_username, update.effective_user.id)
    await message.reply_text(f"✅ Channel added: {channel_username}")


async def remove_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    await query.answer()
    if query.data and query.data.startswith("remove_"):
        channel_id = query.data.split("remove_", 1)[1]
        remove_channel(channel_id)
        await query.edit_message_text(f"✅ Removed channel: {channel_id}")
