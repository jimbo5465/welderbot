"""
نقطه ورود WelderBot — فاز ۱۰ (مدیریت پیمانکار اضافه شد).
این فایل فقط وظیفه سیم‌کشی (wiring) دارد:
  - راه‌اندازی logging
  - مقداردهی اولیه DB
  - ساخت Application
  - ثبت تمام handlers
  - شروع polling

هیچ منطق کسب‌وکار، SQL، یا مقدار ASME در این فایل وجود ندارد.
امنیت: BOT_TOKEN و ADMIN_IDS فقط از متغیرهای محیطی می‌آیند — هیچ مقدار
       hard-code نشده است. هر handler غیر-عمومی پشت auth guard قرار دارد.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# ── ۱. پیکربندی logging — باید قبل از هر چیز دیگری باشد ─────────────────────
_LOG_DIR = Path("logs")
_LOG_DIR.mkdir(exist_ok=True)

_log_level = logging.DEBUG if os.environ.get("WELDERBOT_DEBUG") == "1" else logging.INFO

_fmt = logging.Formatter(
    fmt="%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_stdout_handler = logging.StreamHandler(sys.stdout)
_stdout_handler.setFormatter(_fmt)

_file_handler = logging.handlers.RotatingFileHandler(
    filename=_LOG_DIR / "welderbot.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setFormatter(_fmt)

logging.basicConfig(
    level=_log_level,
    handlers=[_stdout_handler, _file_handler],
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ── ۲. import‌های پروژه — fail-fast: اگر نام اشتباه باشد ImportError می‌دهد ─
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import config
from db.init import init_db

from handlers.menu import get_menu_handlers
from handlers.welders import (
    get_welder_conversation_handler,
    get_welder_plain_handlers,
)
from handlers.test_registration import get_registration_conversation_handler
from handlers.access_management import get_access_management_conversation_handler

# فاز ۹: مدیریت پروژه
from handlers.projects import (
    get_project_conversation_handler,
    get_project_plain_handlers,
)

# 🆕 فاز ۱۰: مدیریت پیمانکار
from handlers.contractors import (
    get_contractor_conversation_handler,
    get_contractor_plain_handlers,
)


# ══════════════════════════════════════════════════════════════════════════════
# هندلر سراسری خطا
# ══════════════════════════════════════════════════════════════════════════════

async def global_error_handler(update: object, context) -> None:
    logger.exception(
        "خطای پردازش‌نشده | update=%s | خطا=%s",
        type(update).__name__,
        context.error,
        exc_info=context.error,
    )
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "❌ خطایی رخ داد، لطفاً دوباره تلاش کنید.\n"
                "اگر مشکل ادامه داشت /start را بزنید."
            )
    except Exception:
        logger.exception("خطا در ارسال پیام خطا به کاربر")


# ══════════════════════════════════════════════════════════════════════════════
# هندلر fallback برای ورودی‌های ناشناخته
# ══════════════════════════════════════════════════════════════════════════════

async def unknown_message_handler(update: Update, context) -> None:
    await update.message.reply_text(
        "❓ این دستور شناخته نشد.\n"
        "برای شروع /start را بزنید."
    )


async def unknown_callback_handler(update: Update, context) -> None:
    if update.callback_query:
        await update.callback_query.answer(
            "⚠️ این دکمه دیگر معتبر نیست. لطفاً /start را بزنید.",
            show_alert=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# هندلر /help
# ══════════════════════════════════════════════════════════════════════════════

async def help_command(update: Update, context) -> None:
    await update.message.reply_text(
        "📖 *راهنمای WelderBot*\n\n"
        "/start — شروع و منوی اصلی\n"
        "/cancel — لغو عملیات جاری\n"
        "/help — نمایش این راهنما\n\n"
        "تمام عملیات از طریق دکمه‌های منو انجام می‌شود.\n"
        "برای ثبت آزمون WQT از منوی اصلی استفاده کنید.",
        parse_mode="Markdown",
    )


# ══════════════════════════════════════════════════════════════════════════════
# تابع اصلی
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    logger.info("=" * 60)
    logger.info("در حال راه‌اندازی ربات WelderBot ...")
    logger.info("سطح لاگ: %s", logging.getLevelName(_log_level))
    logger.info("مسیر DB: %s", config.DB_PATH)
    logger.info("مسیر رسانه: %s", config.MEDIA_PATH)
    logger.info("=" * 60)

    if not config.BOT_TOKEN or config.BOT_TOKEN == "PLACEHOLDER_BOT_TOKEN":
        print(
            "\n❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است.\n"
            "   لطفاً قبل از اجرا این دستور را بزنید:\n"
            "   export BOT_TOKEN='توکن_ربات_شما'\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if not config.ADMIN_IDS:
        logger.warning(
            "⚠️ هیچ ADMIN_ID تنظیم نشده است. "
            "متغیر محیطی ADMIN_IDS را تنظیم کنید (مثال: export ADMIN_IDS=123456789)"
        )

    logger.info("در حال مقداردهی اولیه پایگاه داده ...")
    try:
        init_db()
        logger.info("✅ پایگاه داده آماده است.")
    except Exception as exc:
        logger.critical(
            "❌ خطای کشنده در راه‌اندازی پایگاه داده: %s\n"
            "ربات بدون DB اجرا نمی‌شود. مسیر: %s",
            exc,
            config.DB_PATH,
            exc_info=True,
        )
        sys.exit(2)

    logger.info("در حال ساخت Application تلگرام ...")
    app = Application.builder().token(config.BOT_TOKEN).build()

    logger.info("در حال ثبت handlers ...")

    app.add_error_handler(global_error_handler)

    app.add_handler(get_registration_conversation_handler())
    logger.info("  ✓ ConversationHandler ثبت آزمون WQT ثبت شد (۳۰ state)")

    app.add_handler(get_welder_conversation_handler())
    logger.info("  ✓ ConversationHandler جوشکاران ثبت شد")

    app.add_handler(get_access_management_conversation_handler())
    logger.info("  ✓ ConversationHandler مدیریت دسترسی ثبت شد")

    app.add_handler(get_project_conversation_handler())
    logger.info("  ✓ ConversationHandler مدیریت پروژه ثبت شد")

    # 🆕 مدیریت پیمانکار (فاز ۱۰)
    app.add_handler(get_contractor_conversation_handler())
    logger.info("  ✓ ConversationHandler مدیریت پیمانکار ثبت شد")

    for handler in get_menu_handlers():
        app.add_handler(handler)
    app.add_handler(CommandHandler("help", help_command))
    logger.info("  ✓ CommandHandlers ثبت شدند (/start /cancel /help)")

    for handler in get_welder_plain_handlers():
        app.add_handler(handler)
    logger.info("  ✓ CallbackQueryHandlers جوشکاران ثبت شدند")

    for handler in get_project_plain_handlers():
        app.add_handler(handler)
    logger.info("  ✓ CallbackQueryHandlers مدیریت پروژه ثبت شدند")

    # 🆕 CallbackQueryHandlers مستقل مدیریت پیمانکار
    for handler in get_contractor_plain_handlers():
        app.add_handler(handler)
    logger.info("  ✓ CallbackQueryHandlers مدیریت پیمانکار ثبت شدند")

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            unknown_message_handler,
        )
    )
    app.add_handler(
        CallbackQueryHandler(unknown_callback_handler)
    )
    logger.info("  ✓ Fallback handlers ثبت شدند")

    logger.info("✅ تمام handlers ثبت شدند.")
    logger.info("ادمین‌های پیکربندی‌شده: %s", config.ADMIN_IDS or "هیچ‌کدام")

    logger.info("🚀 WelderBot در حال اجرا است. منتظر پیام‌ها...")
    logger.info("برای توقف Ctrl+C را بزنید.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
