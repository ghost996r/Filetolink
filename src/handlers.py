import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src import database
from src.config import ADMIN_ID, FILES_DIR, FILE_EXPIRY_MINUTES, LOG_CHANNEL, MAX_FILE_SIZE_MB

logger = logging.getLogger(__name__)


class FileBotHandlers:
    def __init__(self) -> None:
        self.channels: List[Tuple[str, str]] = database.list_channels()

    def reload_channels(self) -> None:
        self.channels = database.list_channels()

    @staticmethod
    def _target_message(update: Update) -> Optional[Message]:
        if update.message:
            return update.message
        if update.callback_query and update.callback_query.message:
            return update.callback_query.message
        return None

    async def save_user(self, user_id: int, username: Optional[str], first_name: Optional[str]) -> None:
        database.save_user(user_id, username, first_name)

    async def log_user_activity(self, context: ContextTypes.DEFAULT_TYPE, user_id: int, username: Optional[str], first_name: Optional[str], action: str) -> None:
        uname = f"@{username}" if username else "unknown"
        log_msg = (
            "👤 <b>New Activity</b>\n\n"
            f"👤 <b>User:</b> {first_name or 'Unknown'} (<code>{uname}</code>)\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"📝 <b>Action:</b> {action}\n"
            f"⏰ <b>Time:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            await context.bot.send_message(LOG_CHANNEL, log_msg, parse_mode=ParseMode.HTML)
        except Exception:
            logger.exception("Failed to send log activity")

    async def user_in_channels(self, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
        for channel_id, _ in self.channels:
            try:
                member = await context.bot.get_chat_member(channel_id, user_id)
                if member.status in ["left", "kicked"]:
                    return False
            except Exception:
                return False
        return True

    async def handle_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = self._target_message(update)
        if not message or not update.effective_user:
            return

        if update.effective_user.id != ADMIN_ID:
            await message.reply_text("❌ Only admin can upload files!")
            return

        if not any([message.document, message.photo, message.video, message.audio]):
            await message.reply_text("❌ Please send a file (photo/video/document/audio)!")
            return

        file_size_mb = 0
        if message.document and message.document.file_size:
            file_size_mb = message.document.file_size / (1024 * 1024)
        elif message.video and message.video.file_size:
            file_size_mb = message.video.file_size / (1024 * 1024)
        elif message.audio and message.audio.file_size:
            file_size_mb = message.audio.file_size / (1024 * 1024)

        if file_size_mb > MAX_FILE_SIZE_MB:
            await message.reply_text(
                f"❌ File is too large! Max size: {MAX_FILE_SIZE_MB}MB, Your file: {file_size_mb:.2f}MB"
            )
            return

        file_id = str(uuid.uuid4())
        tg_file = (
            await message.document.get_file()
            if message.document
            else await message.photo[-1].get_file()
            if message.photo
            else await message.video.get_file()
            if message.video
            else await message.audio.get_file()
        )

        FILES_DIR.mkdir(parents=True, exist_ok=True)
        file_path = FILES_DIR / file_id
        await tg_file.download_to_drive(str(file_path))

        file_name = (
            message.document.file_name
            if message.document
            else f"{file_id}.jpg"
            if message.photo
            else f"{file_id}.mp4"
            if message.video
            else f"{file_id}.mp3"
        )

        expires_at = (datetime.now() + timedelta(minutes=FILE_EXPIRY_MINUTES)).isoformat()
        database.add_file_record(file_id, str(file_path), file_name, ADMIN_ID, expires_at)

        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start={file_id}"

        keyboard = [[InlineKeyboardButton("🔗 Share Link", url=link)]]
        await message.reply_text(
            (
                "✅ **File Locked Successfully!**\n\n"
                f"📄 **File:** {file_name}\n"
                f"🔗 **Share Link:**\n`{link}`\n\n"
                f"⏰ **Expires:** {FILE_EXPIRY_MINUTES} minutes"
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = self._target_message(update)
        if not message or not update.effective_user:
            return

        user = update.effective_user
        await self.save_user(user.id, user.username, user.first_name)

        if context.args:
            await self.deliver_file(update, context, context.args[0])
            return

        await message.reply_text("🔒 Send me a file to lock it! (Admin only)")

    async def deliver_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str) -> None:
        message = self._target_message(update)
        if not message or not update.effective_user:
            return

        file_data = database.get_active_file(file_id)
        if not file_data:
            await message.reply_text("❌ File not found or expired!")
            return

        if not self.channels:
            await message.reply_text("ℹ️ No channels to join. File coming soon...")
            await self.send_file(update, context, file_data)
            return

        if await self.user_in_channels(context, update.effective_user.id):
            await self.send_file(update, context, file_data)
            return

        keyboard = []
        for _, channel_username in self.channels:
            clean_username = channel_username[1:] if channel_username.startswith("@") else channel_username
            keyboard.append([InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{clean_username}")])
        keyboard.append([InlineKeyboardButton("✅ Joined All?", callback_data=f"check_{file_id}")])

        await message.reply_text(
            f"🔒 **Join all channels first!**\n\n⏰ File expires in {FILE_EXPIRY_MINUTES} minutes.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def send_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE, file_data: Tuple) -> None:
        message = self._target_message(update)
        if not message or not update.effective_user:
            return

        _, file_path, file_name, *_ = file_data

        try:
            with open(Path(file_path), "rb") as content:
                caption = f"📄 **{file_name}**\n\n⏰ Auto-deletes in {FILE_EXPIRY_MINUTES} minutes"
                if file_name.endswith((".mp4", ".avi", ".mkv")):
                    await message.reply_video(content, caption=caption, parse_mode=ParseMode.MARKDOWN)
                elif file_name.endswith((".jpg", ".jpeg", ".png", ".gif")):
                    await message.reply_photo(content, caption=caption, parse_mode=ParseMode.MARKDOWN)
                elif file_name.endswith((".mp3", ".wav", ".flac")):
                    await message.reply_audio(content, caption=caption, parse_mode=ParseMode.MARKDOWN)
                else:
                    await message.reply_document(content, caption=caption, parse_mode=ParseMode.MARKDOWN)

            await self.log_user_activity(
                context,
                update.effective_user.id,
                update.effective_user.username,
                update.effective_user.first_name,
                f"Downloaded: {file_name}",
            )
        except Exception as exc:
            await message.reply_text("❌ Error delivering file!")
            logger.error("File delivery error: %s", exc)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query:
            return

        await query.answer()
        if query.data and query.data.startswith("check_"):
            await self.deliver_file(update, context, query.data.split("_", 1)[1])

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = self._target_message(update)
        if not message or not update.effective_user:
            return

        if update.effective_user.id != ADMIN_ID:
            return

        keyboard = [
            [InlineKeyboardButton("📊 Stats", callback_data="stats")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="broadcast")],
            [InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")],
            [InlineKeyboardButton("➖ Remove Channel", callback_data="remove_channel")],
            [InlineKeyboardButton("📋 Channel List", callback_data="channel_list")],
        ]

        await message.reply_text(
            "🔧 **Admin Panel**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not update.effective_user:
            return

        if update.effective_user.id != ADMIN_ID:
            await query.answer("Unauthorized", show_alert=True)
            return

        await query.answer()

        if query.data == "stats":
            users = database.count_users()
            files = database.count_active_files()
            await query.edit_message_text(
                f"📊 **Stats**\n\n👥 **Users:** {users}\n📁 **Active Files:** {files}",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if query.data == "broadcast":
            await query.edit_message_text("📢 Send a broadcast message (text/media) and I will send to all users.")
            return

        if query.data == "add_channel":
            await query.edit_message_text("➕ Use /addchannel @channelusername")
            return

        if query.data == "remove_channel":
            if not self.channels:
                await query.edit_message_text("No channels to remove.")
                return

            keyboard = []
            for channel_id, channel_username in self.channels:
                keyboard.append(
                    [InlineKeyboardButton(f"❌ {channel_username}", callback_data=f"remove_{channel_id}")]
                )
            await query.edit_message_text("Select channel to remove:", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if query.data == "channel_list":
            if not self.channels:
                await query.edit_message_text("Channel list is empty.")
                return

            text = "📋 **Channel List**\n\n"
            for _, channel_username in self.channels:
                text += f"• {channel_username}\n"
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
            return

        if query.data and query.data.startswith("remove_"):
            channel_id = query.data.split("remove_", 1)[1]
            database.remove_channel(channel_id)
            self.reload_channels()
            await query.edit_message_text(f"✅ Removed channel: {channel_id}")

    async def add_channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = self._target_message(update)
        if not message or not update.effective_user:
            return

        if update.effective_user.id != ADMIN_ID:
            return

        if not context.args:
            await message.reply_text("Usage: /addchannel @channelusername")
            return

        normalized = database.add_channel(context.args[0], update.effective_user.id)
        self.reload_channels()
        await message.reply_text(f"✅ Channel added: {normalized}")
