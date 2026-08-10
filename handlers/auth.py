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

    نقش کاربر را بر اساس وجود هر نوع access_grant فعال تعیین می‌کند.



    فاز ۱۳.۱ (رفع رگرسیون): نسخهٔ قبلی این تابع از get_effective_level(telegram_id)

    بدون project_id/contractor_id استفاده می‌کرد — اما آن تابع عمداً طوری طراحی

    شده که بدون context، سطح ۲ و ۳ را هرگز تشخیص نمی‌دهد (چون تطبیق‌شان به

    project_id/contractor_id مشخص نیاز دارد). نتیجه: کاربران خالص سطح ۲/۳

    (بدون هیچ grant سطح ۱) نمی‌توانستند اصلاً وارد ربات شوند.



    این نسخه مستقیماً access_grants را می‌خواند — «آیا حداقل یک grant فعال

    دارد؟» — بدون نیاز به context خاص.



    خروجی:

        'admin'    اگر سطح ۱ باشد

        'operator' اگر حداقل یک access_grant فعال دیگر (سطح ۲ یا ۳) داشته باشد

        None       اگر هیچ access_grant فعالی نداشته باشد

    """

    if telegram_id in config.ADMIN_IDS:

        return ROLE_ADMIN



    grants = get_access_grants_by_telegram(telegram_id, active_only=True)

    if not grants:

        return None



    has_level1 = any(g["level"] == LEVEL_PROJECT_MANAGER for g in grants)

    return ROLE_ADMIN if has_level1 else ROLE_OPERATOR





def is_admin(telegram_id: int) -> bool:

    """بررسی می‌کند آیا کاربر سطح ۱ (مدیر سراسری) است."""

    return get_role(telegram_id) == ROLE_ADMIN





def is_authenticated(telegram_id: int) -> bool:

    """بررسی می‌کند آیا کاربر حداقل یک access_grant فعال دارد (هر سطحی)."""

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

def get_my_project_ids(telegram_id: int) -> list[int] | None:
    """
    پروژه‌هایی که این کاربر حق دیدن‌شان را دارد.
    خروجی None یعنی «همه» (سطح ۱). خروجی [] یعنی هیچ پروژه‌ای.
    """
    if get_effective_level(telegram_id) == LEVEL_PROJECT_MANAGER:
        return None
    grants = get_access_grants_by_telegram(telegram_id, active_only=True)
    return sorted({g["project_id"] for g in grants if g["project_id"] is not None})


def get_my_operator_contractor(telegram_id: int, project_id: int) -> int | None:
    """برای سطح ۳: در این پروژه، فقط مجاز به کدام پیمانکار است؟"""
    grants = get_access_grants_by_telegram(telegram_id, active_only=True)
    for g in grants:
        if g["level"] == LEVEL_OPERATOR and g["project_id"] == project_id:
            return g["contractor_id"]
    return None

def get_my_contractor_id_for_project(telegram_id: int, project_id: int) -> int | None:
    """
    اگر کاربر در این پروژه محدود به یک پیمانکار خاص است (سطح ۳/اپراتور)،
    همان contractor_id را برمی‌گرداند.

    خروجی:
        None → کاربر سطح ۱ یا ۲ است (همهٔ پیمانکاران این پروژه برایش مجازند)
        int  → کاربر سطح ۳ است، فقط همین پیمانکار مجاز است
    """
    level_here = get_effective_level(telegram_id, project_id=project_id)
    if level_here in (LEVEL_PROJECT_MANAGER, LEVEL_CONTRACTOR_MANAGER):
        return None

    grants = get_access_grants_by_telegram(telegram_id, active_only=True)
    for g in grants:
        if g["level"] == LEVEL_OPERATOR and g["project_id"] == project_id:
            return g["contractor_id"]
    return None
