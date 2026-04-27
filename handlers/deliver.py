import asyncio
from contextlib import suppress
from pathlib import Path

from telegram import Message, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from config import FILE_EXPIRY_MINUTES, NEVER_EXPIRE_LINKS, REQUIRED_CHANNELS
from handlers.channel import build_join_keyboard, user_in_channels
from services.file_service import get_active_file, log_download
from utils.helpers import get_target_message

from handlers.channel import user_in_required_channels, build_join_keyboard_for_required_channels

AUTO_DELETE_MINUTES = 15
AUTO_DELETE_SECONDS = AUTO_DELETE_MINUTES * 60


def _is_secondary_bot(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.application and context.application.bot_data.get("role") == "secondary")


def _schedule_delete(context: ContextTypes.DEFAULT_TYPE, message_obj: Message, delay_seconds: int) -> None:
    async def _delete_later() -> None:
        await asyncio.sleep(delay_seconds)
        with suppress(BadRequest, Forbidden):
            await context.bot.delete_message(chat_id=message_obj.chat_id, message_id=message_obj.message_id)

    asyncio.create_task(_delete_later())


async def send_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_data) -> None:
    message = get_target_message(update)
    if not message or not update.effective_user:
        return

    _, file_path, file_name, _, _, _, storage_chat_id, storage_message_id = file_data

    delivered_message: Message | None = None

    try:
        if storage_chat_id and storage_message_id:
            delivered_message = await context.bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=storage_chat_id,
                message_id=storage_message_id,
            )
        else:
            with open(Path(file_path), "rb") as content:
                caption = f"📄 {file_name}"
                if file_name.endswith((".mp4", ".avi", ".mkv")):
                    delivered_message = await message.reply_video(content, caption=caption)
                elif file_name.endswith((".jpg", ".jpeg", ".png", ".gif")):
                    delivered_message = await message.reply_photo(content, caption=caption)
                elif file_name.endswith((".mp3", ".wav", ".flac")):
                    delivered_message = await message.reply_audio(content, caption=caption)
                else:
                    delivered_message = await message.reply_document(content, caption=caption)

        await log_download(
            context,
            update.effective_user.id,
            update.effective_user.username,
            update.effective_user.first_name,
            file_name,
        )

        if _is_secondary_bot(context) and delivered_message:
            is_video = file_name.lower().endswith((".mp4", ".avi", ".mkv", ".mov", ".webm"))
            media_label = "video" if is_video else "file"
            warning_message = await message.reply_text(
                f"Please forward or save this {media_label} now. It will be deleted from this chat in {AUTO_DELETE_MINUTES} minutes."
            )
            _schedule_delete(context, delivered_message, AUTO_DELETE_SECONDS)
            _schedule_delete(context, warning_message, AUTO_DELETE_SECONDS)
    except Forbidden:
        await message.reply_text(
            "❌ BOT_TOKEN1 cannot access storage channel. Please add BOT_TOKEN1 bot to STORAGE_CHANNEL_ID as admin."
        )
    except BadRequest:
        await message.reply_text("❌ File source message not accessible or already deleted.")
    except Exception:
        await message.reply_text("❌ Error delivering file! Please try again.")


async def deliver_file(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str) -> None:
    message = get_target_message(update)
    if not message or not update.effective_user:
        return

    file_data = get_active_file(file_id)
    if not file_data:
        await message.reply_text("❌ File not found!")
        return

    if await user_in_channels(context, update.effective_user.id):
        await send_file(update, context, file_data)
        return

    prompt = "🔒 Join all channels first!"
    if not NEVER_EXPIRE_LINKS:
        prompt += f"\n\n⏰ File expires in {FILE_EXPIRY_MINUTES} minutes."

    await message.reply_text(prompt, reply_markup=build_join_keyboard(file_id))


async def deliver_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    if query.data.startswith("check_"):
        file_id = query.data.split("_", 1)[1]
        
        # For secondary bot (BOT_TOKEN1), check channel membership if required
        if _is_secondary_bot(context) and REQUIRED_CHANNELS:
            is_member = await user_in_required_channels(context, query.from_user.id)
            if not is_member:
                await query.answer(
                    "❌ You still haven't passed the channel check. If the links are private invite links, add a verification target with `|@channelusername` or `|-100...`.",
                    show_alert=True,
                )
                return
        
        await deliver_file(update, context, file_id)
