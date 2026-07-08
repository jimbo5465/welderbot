"""
ماژول auth — احراز هویت و کنترل دسترسی مبتنی بر نقش.
نقش‌ها: admin (مدیر کامل) و operator (اپراتور محدود).
شناسه admin‌ها از config.ADMIN_IDS می‌آیند — هیچ مقدار hard-code نشده.
"""

from __future__ import annotations

import functools
import logging
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import config
from db.models import get_user_by_telegram_id, add_user

logger = logging.getLogger(__name__)

# ── ثابت‌های نقش ─────────────────────────────────────────────────────────────
ROLE_ADMIN    = "admin"
ROLE_OPERATOR = "operator"


# ══════════════════════════════════════════════════════════════════════════════
# توابع اصلی احراز هویت
# ══════════════════════════════════════════════════════════════════════════════

def get_role(telegram_id: int) -> str | None:
    """
    نقش کاربر را بر اساس telegram_id تعیین می‌کند.

    ورودی:
        telegram_id: شناسه تلگرام کاربر

    خروجی:
        'admin' / 'operator' / None (اگر ثبت نشده یا غیرفعال باشد)
    """
    # بررسی ADMIN_IDS از config — بدون نیاز به DB
    if telegram_id in config.ADMIN_IDS:
        return ROLE_ADMIN

    # بررسی DB برای operator‌های ثبت‌شده
    user = get_user_by_telegram_id(telegram_id)
    if user and user.get("is_active") == 1:
        return user.get("role")

    return None


def is_admin(telegram_id: int) -> bool:
    """بررسی می‌کند آیا کاربر نقش admin دارد."""
    return get_role(telegram_id) == ROLE_ADMIN


def is_authenticated(telegram_id: int) -> bool:
    """بررسی می‌کند آیا کاربر ثبت‌شده و فعال است (admin یا operator)."""
    return get_role(telegram_id) is not None


async def _deny(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پیام «دسترسی غیرمجاز» را به کاربر ارسال می‌کند."""
    text = "⛔ دسترسی غیرمجاز.\nشما اجازه دسترسی به این بخش را ندارید."
    if update.callback_query:
        await update.callback_query.answer(text, show_alert=True)
    elif update.message:
        await update.message.reply_text(text)


# ══════════════════════════════════════════════════════════════════════════════
# دکوراتورهای کنترل دسترسی
# ══════════════════════════════════════════════════════════════════════════════

def require_auth(func: Callable) -> Callable:
    """
    دکوراتور: فقط کاربران ثبت‌شده (admin یا operator) مجاز هستند.
    اگر کاربر ناشناس باشد → پیام «دسترسی غیرمجاز» و توقف.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or not is_authenticated(user.id):
            await _deny(update, context)
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapper


def require_admin(func: Callable) -> Callable:
    """
    دکوراتور: فقط admin‌ها مجاز هستند.
    اگر کاربر admin نباشد → پیام «دسترسی غیرمجاز» و توقف.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user or not is_admin(user.id):
            await _deny(update, context)
            return ConversationHandler.END
        return await func(update, context, *args, **kwargs)
    return wrapper


async def ensure_user_registered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """
    بررسی می‌کند کاربر در DB ثبت شده است. اگر admin است و در DB نیست، ثبت می‌کند.

    خروجی:
        نقش کاربر ('admin'/'operator') یا None اگر مجاز نباشد
    """
    tg_user = update.effective_user
    if not tg_user:
        return None

    tid = tg_user.id
    role = get_role(tid)

    if role == ROLE_ADMIN:
        # اگر admin در DB نیست، خودکار ثبت می‌شود
        existing = get_user_by_telegram_id(tid)
        if not existing:
            try:
                add_user(
                    telegram_id=tid,
                    full_name=tg_user.full_name or "Admin",
                    role=ROLE_ADMIN,
                )
                logger.info("ادمین جدید در DB ثبت شد: %d", tid)
            except Exception:
                logger.exception("خطا در ثبت خودکار ادمین: %d", tid)

    return role
