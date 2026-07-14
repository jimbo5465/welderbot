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
from db.models import get_user_by_telegram_id, add_user, get_access_grants_by_telegram

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


# ══════════════════════════════════════════════════════════════════════════════
# سیستم دسترسی سلسله‌مراتبی + Scoped — فاز ۸
# این بخش اضافه می‌شود، جایگزین require_auth/require_admin بالا نمی‌شود.
# ══════════════════════════════════════════════════════════════════════════════

LEVEL_PROJECT_MANAGER    = 1   # سراسری — می‌سازد/ویرایش/حذف پروژه
LEVEL_CONTRACTOR_MANAGER = 2   # محدود به یک project_id — مدیریت پیمانکار همان پروژه
LEVEL_OPERATOR           = 3   # محدود به یک contractor_id — فقط انتخاب/ثبت تست


def get_effective_level(
    telegram_id: int,
    project_id: int | None = None,
    contractor_id: int | None = None,
) -> int | None:
    """
    بالاترین سطح دسترسی مؤثر کاربر را برای یک context مشخص برمی‌گرداند.
    با ارث‌بری: سطح ۱ همیشه سطح ۲ و ۳ را هم شامل می‌شود، سطح ۲ سطح ۳ را.
    """
    if telegram_id in config.ADMIN_IDS:
        return LEVEL_PROJECT_MANAGER

    grants = get_access_grants_by_telegram(telegram_id, active_only=True)
    if not grants:
        return None

    best_level = None
    for g in grants:
        if g["level"] == LEVEL_PROJECT_MANAGER:
            best_level = _better_level(best_level, 1)
            continue
        if g["level"] == LEVEL_CONTRACTOR_MANAGER:
            if project_id is not None and g["project_id"] == project_id:
                best_level = _better_level(best_level, 2)
            continue
        if g["level"] == LEVEL_OPERATOR:
            if contractor_id is not None and g["contractor_id"] == contractor_id:
                best_level = _better_level(best_level, 3)
            continue

    return best_level


def _better_level(current: int | None, candidate: int) -> int:
    """عدد سطح کوچک‌تر = دسترسی بالاتر (۱ از ۲ قوی‌تر است)."""
    if current is None:
        return candidate
    return min(current, candidate)


def can_manage_projects(telegram_id: int) -> bool:
    """آیا کاربر می‌تواند پروژه بسازد/ویرایش/حذف کند؟ (فقط سطح ۱)"""
    return get_effective_level(telegram_id) == LEVEL_PROJECT_MANAGER


def can_manage_contractors(telegram_id: int, project_id: int) -> bool:
    """آیا کاربر می‌تواند در این پروژه پیمانکار بسازد/ویرایش/حذف کند؟ (سطح ۱ یا ۲)"""
    level = get_effective_level(telegram_id, project_id=project_id)
    return level in (LEVEL_PROJECT_MANAGER, LEVEL_CONTRACTOR_MANAGER)


def can_select_contractor(telegram_id: int, project_id: int, contractor_id: int) -> bool:
    """آیا کاربر می‌تواند این پیمانکار خاص را انتخاب کند؟ (هر سه سطح، در scope خودشان)"""
    level = get_effective_level(telegram_id, project_id=project_id, contractor_id=contractor_id)
    return level is not None


def can_grant_level3(telegram_id: int, project_id: int) -> bool:
    """آیا کاربر می‌تواند برای پیمانکارهای این پروژه، اپراتور سطح ۳ معرفی کند؟"""
    return can_manage_contractors(telegram_id, project_id)
