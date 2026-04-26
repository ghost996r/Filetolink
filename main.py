import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import Application, CallbackQueryHandler, ChatJoinRequestHandler, CommandHandler, MessageHandler, filters

from config import BOT_TOKEN, BOT_TOKEN1, BROADCAST_CLEANUP_INTERVAL_MINUTES, CLEANUP_INTERVAL_MINUTES
from database.db import init_db
from handlers.admin import admin_callback_handler, admin_text_handler, cancel_admin_command, admin_panel
from handlers.channel import add_channel_command, channel_join_request_handler, remove_channel_callback
from handlers.deliver import deliver_callback_handler
from handlers.start import start_handler
from handlers.upload import copy_link_callback_handler, upload_handler
from scheduler.cleanup import cleanup_broadcasts, cleanup_expired_files
from utils.helpers import ADMIN_STATE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/health"}:
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _start_health_server_if_needed() -> None:
    port_raw = os.getenv("PORT", "5000").strip()
    try:
        port = int(port_raw)
    except ValueError:
        logger.warning("Invalid PORT value: %s", port_raw)
        return

    def _serve() -> None:
        try:
            httpd = HTTPServer(("0.0.0.0", port), _HealthHandler)
            logger.info("Health server running at http://localhost:%s/health", port)
            httpd.serve_forever()
        except Exception as exc:
            logger.error("Health server failed: %s", exc)

    threading.Thread(target=_serve, name="render-health-server", daemon=True).start()


async def post_init(app: Application) -> None:
    scheduler = AsyncIOScheduler(event_loop=asyncio.get_running_loop())
    scheduler.add_job(cleanup_expired_files, "interval", minutes=CLEANUP_INTERVAL_MINUTES, kwargs={"bot": app.bot})
    scheduler.add_job(cleanup_broadcasts, "interval", minutes=BROADCAST_CLEANUP_INTERVAL_MINUTES)
    scheduler.start()
    app.bot_data["scheduler"] = scheduler
    logger.info("Scheduler initialized")


async def post_stop(app: Application) -> None:
    scheduler = app.bot_data.get("scheduler")
    if scheduler:
        scheduler.shutdown()
        logger.info("Scheduler stopped")


def build_application(bot_token: str, bot_role: str) -> Application:
    application = Application.builder().token(bot_token).build()
    application.bot_data["role"] = bot_role

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(ChatJoinRequestHandler(channel_join_request_handler))
    application.add_handler(CallbackQueryHandler(deliver_callback_handler, pattern=r"^check_"))

    if bot_role == "primary":
        application.add_handler(CommandHandler("admin", admin_panel))
        application.add_handler(CommandHandler("addchannel", add_channel_command))
        application.add_handler(CommandHandler("cancel", cancel_admin_command))

        application.add_handler(
            CallbackQueryHandler(
                admin_callback_handler,
                pattern=r"^(stats|broadcast|add_channel|remove_channel|channel_list)$",
            )
        )
        application.add_handler(
            CallbackQueryHandler(remove_channel_callback, pattern=r"^remove_"),
        )
        application.add_handler(
            CallbackQueryHandler(copy_link_callback_handler, pattern=r"^copy_"),
        )

        media_filter = filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO
        application.add_handler(MessageHandler(media_filter, upload_handler))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_handler))

        application.post_init = post_init
        application.post_stop = post_stop

    return application


def run_bot(bot_token: str, bot_role: str) -> None:
    if bot_token == "YOUR_BOT_TOKEN_HERE":
        logger.warning("%s token is not configured. Set it in .env before running.", bot_role)

    init_db()
    logger.info("Starting bot in %s mode", bot_role)
    application = build_application(bot_token, bot_role)
    application.run_polling()


def run() -> None:
    _start_health_server_if_needed()

    if BOT_TOKEN1 and BOT_TOKEN1 != BOT_TOKEN:
        secondary_thread = threading.Thread(
            target=run_bot,
            args=(BOT_TOKEN1, "secondary"),
            daemon=True,
            name="secondary-bot"
        )
        secondary_thread.start()
        logger.info("Secondary bot thread started")
    elif BOT_TOKEN1 == BOT_TOKEN:
        logger.warning("BOT_TOKEN1 matches BOT_TOKEN. Secondary bot will not be started.")

    run_bot(BOT_TOKEN, "primary")


if __name__ == "__main__":
    run()
