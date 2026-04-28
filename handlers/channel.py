from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database.db import add_channel, list_channels, remove_channel
from utils.helpers import get_target_message, is_admin, normalize_channel_username

# { user_id -> file_id } - tracks which file user was trying to access
_PENDING_JOIN_ACCESS: dict[int, str] = {}


async def user_in_channels(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Check if user is member of all database channels."""
    channels = list_channels()
    if not channels:
        return True
    for channel_id, _ in channels:
        try:
            member = await context.bot.get_chat_member(channel_id, user_id)
            if member.status in ["left", "kicked"]:
                return False
        except Exception:
            # Private channel — bot cannot check membership
            # Check if user has pending join request instead
            if user_id not in _PENDING_JOIN_ACCESS:
                return False
    return True


def build_join_keyboard(file_id: str) -> InlineKeyboardMarkup:
    """Build keyboard with join buttons for all database channels."""
    keyboard = []
    for channel_id, channel_username in list_channels():
        if channel_username and not channel_username.startswith("-"):
            clean = channel_username.lstrip("@")
            keyboard.append([InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{clean}")])
        else:
            # Private channel — show request button
            keyboard.append([InlineKeyboardButton("📢 Send Join Request", url=f"https://t.me/c/{str(channel_id).replace('-100', '')}")])
    keyboard.append([InlineKeyboardButton("✅ Done? Try Again", callback_data=f"check_{file_id}")])
    return InlineKeyboardMarkup(keyboard)


def set_pending_file(user_id: int, file_id: str) -> None:
    """Store which file a user was trying to access before joining."""
    _PENDING_JOIN_ACCESS[user_id] = file_id


def get_pending_file(user_id: int) -> str | None:
    """Get and clear the pending file for a user."""
    return _PENDING_JOIN_ACCESS.pop(user_id, None)


async def channel_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detect join request — deliver pending file WITHOUT approving request."""
    join_request = update.chat_join_request
    if not join_request:
        return

    user_id = join_request.from_user.id
    request_chat_id = join_request.chat.id

    # Check against all database channels
    channels = list_channels()
    channel_ids = []
    for ch_id, _ in channels:
        try:
            channel_ids.append(int(ch_id))
        except (ValueError, TypeError):
            pass

    if request_chat_id not in channel_ids:
        return

    # User sent join request — mark as pending and deliver file
    file_id = get_pending_file(user_id)
    if file_id:
        from handlers.deliver import send_file_by_id
        await send_file_by_id(update, context, file_id)
    else:
        try:
            await join_request.from_user.send_message(
                "✅ Join request received!\n\nNow click your file link again to get the file."
            )
        except Exception:
            pass


async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = get_target_message(update)
    if not message or not update.effective_user:
        return

    if not is_admin(update.effective_user.id, ADMIN_ID):
        return

    if not context.args:
        await message.reply_text("Usage: /addchannel @channelusername or channel_id")
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
