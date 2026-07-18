"""
ماژول menu — دستور /start، منوی اصلی، و ناوبری کلی.
همه متن‌های UI فارسی هستند.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
)

from handlers.auth import ensure_user_registered, require_auth, ROLE_ADMIN
from db.models import register_pending_user
from handlers.keyboards import main_menu_keyboard, back_to_main_keyboard

logger = logging.getLogger(__name__)

# ── متن‌های UI ────────────────────────────────────────────────────────────────
_MSG_WELCOME_ADMIN = (
    "👋 خوش آمدید، مدیر عزیز!\n"
    "شما با دسترسی کامل به سیستم وارد شده‌اید.\n\n"
    "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
)
_MSG_WELCOME_OPERATOR = (
    "👋 خوش آمدید!\n"
    "شما به عنوان اپراتور وارد شده‌اید.\n\n"
    "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:"
)
_MSG_NOT_REGISTERED = (
    "⚠️ حساب کاربری شما در سیستم ثبت نشده است.\n"
    "لطفاً با مدیر سیستم تماس بگیرید تا دسترسی شما فعال شود."
)
_MSG_BACK_TO_MENU = "🏠 منوی اصلی:"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    هندلر دستور /start.
    نقش کاربر را تشخیص می‌دهد و منوی مناسب را نمایش می‌دهد.
    """
    try:
        tg_user = update.effective_user
        if not tg_user:
            return

        # هر کاربری که /start می‌زند، صرف‌نظر از دسترسی، در pending_users ثبت
        # می‌شود — تا ادمین بتواند بعداً او را برای اعطای دسترسی انتخاب کند
        register_pending_user(
            telegram_id=tg_user.id,
            full_name=tg_user.full_name or "بدون نام",
            username=tg_user.username,
        )

        # تشخیص نقش و ثبت خودکار admin در DB
        role = await ensure_user_registered(update, context)

        if role is None:
            await update.message.reply_text(_MSG_NOT_REGISTERED)
            return

        # ذخیره نقش در context برای استفاده بعدی
        context.user_data["role"] = role

        msg = _MSG_WELCOME_ADMIN if role == ROLE_ADMIN else _MSG_WELCOME_OPERATOR
        await update.message.reply_text(
            msg,
            reply_markup=main_menu_keyboard(tg_user.id),
        )

    except Exception:
        logger.exception("خطا در هندلر /start برای کاربر %s", update.effective_user)
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره /start را بزنید.")


@require_auth
async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    هندلر callback دکمه «بازگشت به منوی اصلی».
    callback_data: menu:main
    """
    try:
        query = update.callback_query
        await query.answer()

        tg_user = update.effective_user
        role = context.user_data.get("role")
        if not role:
            from handlers.auth import get_role
            role = get_role(tg_user.id) if tg_user else None

        if not role:
            await query.edit_message_text(_MSG_NOT_REGISTERED)
            return

        context.user_data["role"] = role
        await query.edit_message_text(
            _MSG_BACK_TO_MENU,
            reply_markup=main_menu_keyboard(tg_user.id),
        )

    except Exception:
        logger.exception("خطا در main_menu_callback")
        if update.callback_query:
            await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


@require_auth

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    """

    هندلر دستور /cancel — هر مکالمه فعالی را پاک می‌کند و به منو برمی‌گردد.

    """

    try:

        tg_user = update.effective_user



        # پاکسازی کامل داده‌های مکالمه

        context.user_data.clear()



        role = await ensure_user_registered(update, context)

        context.user_data["role"] = role



        msg = "❌ عملیات لغو شد.\n\n" + _MSG_BACK_TO_MENU

        if update.message and tg_user:

            await update.message.reply_text(

                msg,

                reply_markup=main_menu_keyboard(tg_user.id),

            )



        return ConversationHandler.END



    except Exception:

        logger.exception("خطا در cancel_command")

        return ConversationHandler.END



def get_menu_handlers() -> list:
    """
    فهرست handler‌های منو را برمی‌گرداند.
    در main.py ثبت می‌شوند.
    """
    return [
        CommandHandler("start", start_command),
        CommandHandler("cancel", cancel_command),
        CallbackQueryHandler(main_menu_callback, pattern=r"^menu:main$"),
    ]
