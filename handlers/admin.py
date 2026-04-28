from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database.db import count_active_files, count_users, list_channels
from services.broadcast import broadcast_message
from utils.helpers import ADMIN_STATE, get_target_message, is_admin, parse_quoted_parts
from handlers.channel import add_channel_command, remove_channel_callback


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = get_target_message(update)
    if not message or not update.effective_user:
        return

    if not is_admin(update.effective_user.id, ADMIN_ID):
        return

    keyboard = [
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="broadcast")],
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")],
        [InlineKeyboardButton("➖ Remove Channel", callback_data="remove_channel")],
        [InlineKeyboardButton("📋 Channel List", callback_data="channel_list")],
    ]
    await message.reply_text("🔧 **Admin Panel**", reply_markup=InlineKeyboardMarkup(keyboard))


async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not update.effective_user:
        return

    if not is_admin(update.effective_user.id, ADMIN_ID):
        await query.answer("Unauthorized", show_alert=True)
        return

    await query.answer()
    if query.data == "stats":
        await query.edit_message_text(
            f"📊 **Stats**\n\n👥 **Users:** {count_users()}\n📁 **Active Files:** {count_active_files()}",
        )
    elif query.data == "broadcast":
        ADMIN_STATE[update.effective_user.id] = "BROADCAST"
        await query.edit_message_text("📢 Send a broadcast message (text/media) and I will send to all users.")
    elif query.data == "add_channel":
        ADMIN_STATE[update.effective_user.id] = "ADD_CHANNEL"
        await query.edit_message_text("➕ Send channel in format: \"@channel\" \"Button Name\"")
    elif query.data == "remove_channel":
        channels = list_channels()
        if not channels:
            await query.edit_message_text("No channels to remove.")
            return
        keyboard = [[InlineKeyboardButton(channel_username, callback_data=f"remove_{channel_id}")] for channel_id, channel_username, _ in channels]
        await query.edit_message_text("Select channel to remove:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data == "channel_list":
        channels = list_channels()
        if not channels:
            await query.edit_message_text("Channel list is empty.")
            return
        text = "📋 **Channel List**\n\n"
        for _, channel_username, invite_link in channels:
            text += f"• {channel_username}"
            if invite_link:
                text += f" 🔗"
            text += "\n"
        await query.edit_message_text(text)


async def admin_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not update.effective_user:
        return

    if not is_admin(update.effective_user.id, ADMIN_ID):
        return

    state = ADMIN_STATE.get(update.effective_user.id)
    if state == "ADD_CHANNEL":
        parts = parse_quoted_parts(message.text or "")
        if not parts:
            await message.reply_text('Use: "@channelusername" "Button Name"')
            return

        channel_id = parts[0]
        channel_name = parts[1] if len(parts) > 1 else "Join Channel"
        from database.db import add_channel
        from utils.helpers import normalize_channel_username

        normalized = add_channel(normalize_channel_username(channel_id), update.effective_user.id)
        ADMIN_STATE.pop(update.effective_user.id, None)
        await message.reply_text(f"✅ Channel added: {normalized}\nName: {channel_name}")
        return

    if state == "BROADCAST":
        success, total = await broadcast_message(message, context)
        ADMIN_STATE.pop(update.effective_user.id, None)
        await message.reply_text(f"✅ Broadcast done! {success}/{total} users reached.")


async def cancel_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = get_target_message(update)
    if not message or not update.effective_user:
        return

    ADMIN_STATE.pop(update.effective_user.id, None)
    await message.reply_text("✅ Cancelled.")
