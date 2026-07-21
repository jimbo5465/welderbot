"""
ماژول projects — مدیریت چرخهٔ حیات پروژه (فاز ۹).

قوانین قفل‌شده:
  - ایجاد / rename / خاتمه / فعال‌سازی مجدد: فقط سطح ۱ (can_manage_projects)
  - خاتمه = soft (is_active=0)، قابل بازگشت، بدون تأیید دوم اضافه
    (چون سطح ۱ خودش هم درخواست‌دهنده و هم تصمیم‌گیرندهٔ نهایی است)
  - نام پروژه یکتا می‌ماند حتی بعد از خاتمه (UNIQUE در دیتابیس، این‌جا فقط
    IntegrityError آن را پیام فارسی می‌کند)
  - خاتمه هیچ رکورد وابسته‌ای (پیمانکار/جوشکار/صلاحیت) را دست‌کاری نمی‌کند

⚠️ نکات ادغام (پیش از استفاده بررسی کنید):
  1. فرض شده `can_manage_projects(telegram_id) -> bool` در handlers/auth.py
     موجود است (طبق CONTRACTS.md فاز ۸). اگر امضای واقعی متفاوت است،
     فقط تابع _guard_level1 پایین را اصلاح کنید — بقیهٔ فایل دست‌نخورده می‌ماند.
  2. توابع کیبورد (`projects_list_keyboard`, `project_detail_keyboard`)
     در فایل جداگانهٔ keyboards_project_additions.py پیشنهاد شده‌اند —
     باید به handlers/keyboards.py منتقل شوند.
  3. اعتبارسنجی نام پروژه عمداً از validate_name (که برای اسم اشخاص است)
     استفاده نمی‌کند — یک تابع محلی ساده در همین فایل تعریف شده.
"""

from __future__ import annotations

import logging
import sqlite3

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from db.models import (
    add_project,
    list_projects,
    get_project_by_id,
    update_project_name,
    set_project_inactive,
    reactivate_project,
    get_project_stats,
)
from handlers.auth import require_auth, can_manage_projects
from handlers.keyboards import (
    projects_list_keyboard,
    project_detail_keyboard,
    confirm_keyboard,
    back_to_main_keyboard,
    main_menu_keyboard,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# state های ConversationHandler
# ══════════════════════════════════════════════════════════════════════════════

(
    PROJ_CRUD_NAME,         # ورود نام در ایجاد پروژه جدید
    PROJ_CRUD_EDIT_NAME,    # ورود نام جدید در rename
    PROJ_CRUD_CONFIRM_TERM, # تأیید خاتمهٔ پروژه
) = range(3)

_KEY_EDIT_ID = "proj_edit_id"
_KEY_TERM_ID = "proj_term_id"

_MAX_NAME_LEN = 100


# ══════════════════════════════════════════════════════════════════════════════
# توابع کمکی
# ══════════════════════════════════════════════════════════════════════════════

def _validate_project_name(text: str) -> str | None:
    """
    نام پروژه را اعتبارسنجی می‌کند. برخلاف نام جوشکار، اعداد و علائم
    معمول (فاز ۲، پست برق ۴۰۰kV و ...) مجاز است.

    خروجی:
        رشتهٔ strip‌شده اگر معتبر بود، وگرنه None
    """
    name = (text or "").strip()
    if not name:
        return None
    if len(name) > _MAX_NAME_LEN:
        return None
    return name


async def _guard_level1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    بررسی می‌کند کاربر سطح ۱ (مدیر سراسری) است. اگر نه، پیام رد می‌فرستد
    و False برمی‌گرداند تا caller بلافاصله return کند.
    """
    telegram_id = update.effective_user.id
    if not can_manage_projects(telegram_id):
        if update.callback_query:
            await update.callback_query.answer(
                "⛔ فقط مدیر سراسری به مدیریت پروژه دسترسی دارد.", show_alert=True
            )
        elif update.message:
            await update.message.reply_text("⛔ فقط مدیر سراسری به مدیریت پروژه دسترسی دارد.")
        return False
    return True


def _format_project_card(project: dict, stats: dict | None = None) -> str:
    status = "✅ فعال" if project.get("is_active") else "⛔ خاتمه‌یافته"
    lines = [
        f"📁 *{project['name']}*",
        f"وضعیت: {status}",
    ]
    if stats is not None:
        lines.append(f"🏢 پیمانکار فعال: {stats['active_contractors']}")
        lines.append(f"📋 صلاحیت فعال: {stats['active_qualifications']}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# فهرست و جزئیات پروژه (هندلرهای ساده — غیر مکالمه‌ای)
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def show_projects_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نمایش فهرست همهٔ پروژه‌ها (فعال و خاتمه‌یافته) با وضعیت.
    callback_data: menu:projects
    فقط سطح ۱.
    """
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update, context):
            return

        projects = list_projects(active_only=False)
        if not projects:
            await query.edit_message_text(
                "⚠️ هنوز هیچ پروژه‌ای ثبت نشده است.",
                reply_markup=projects_list_keyboard([]),
            )
            return

        await query.edit_message_text(
            f"📁 فهرست پروژه‌ها (تعداد: {len(projects)}):",
            reply_markup=projects_list_keyboard(projects),
        )

    except Exception:
        logger.exception("خطا در show_projects_menu")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


@require_auth
async def project_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نمایش جزئیات یک پروژه + شمار پیمانکار/صلاحیت فعال.
    callback_data: proj:ID
    """
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update, context):
            return

        project_id = int(query.data.split(":")[1])
        project = get_project_by_id(project_id)
        if not project:
            await query.edit_message_text(
                "⚠️ پروژه یافت نشد.", reply_markup=back_to_main_keyboard()
            )
            return

        stats = get_project_stats(project_id)
        await query.edit_message_text(
            _format_project_card(project, stats),
            parse_mode="Markdown",
            reply_markup=project_detail_keyboard(project),
        )

    except Exception:
        logger.exception("خطا در project_detail_callback")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


@require_auth
async def reactivate_project_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    فعال‌سازی مجدد پروژهٔ خاتمه‌یافته. بدون تأیید دوم (سطح ۱ خودش تصمیم‌گیرنده است).
    callback_data: proj_reactivate:ID
    """
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update, context):
            return

        project_id = int(query.data.split(":")[1])
        project = get_project_by_id(project_id)
        if not project:
            await query.edit_message_text(
                "⚠️ پروژه یافت نشد.", reply_markup=back_to_main_keyboard()
            )
            return

        reactivate_project(project_id)
        logger.info("پروژه دوباره فعال شد: id=%d", project_id)

        project = get_project_by_id(project_id)
        stats = get_project_stats(project_id)
        await query.edit_message_text(
            "✅ پروژه دوباره فعال شد.\n\n" + _format_project_card(project, stats),
            parse_mode="Markdown",
            reply_markup=project_detail_keyboard(project),
        )

    except Exception:
        logger.exception("خطا در reactivate_project_callback")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


# ══════════════════════════════════════════════════════════════════════════════
# ایجاد پروژه جدید
# ══════════════════════════════════════════════════════════════════════════════

async def add_project_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع مکالمهٔ ایجاد پروژه جدید.
    callback_data: proj_new
    """
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update, context):
            return ConversationHandler.END

        await query.edit_message_text("📁 نام پروژهٔ جدید را وارد کنید:")
        return PROJ_CRUD_NAME

    except Exception:
        logger.exception("خطا در add_project_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def add_project_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام و ثبت پروژهٔ جدید."""
    try:
        name = _validate_project_name(update.message.text)
        if name is None:
            await update.message.reply_text(
                f"❌ نام نامعتبر است. حداکثر {_MAX_NAME_LEN} کاراکتر و غیرخالی وارد کنید:"
            )
            return PROJ_CRUD_NAME

        try:
            project_id = add_project(name)
        except sqlite3.IntegrityError:
            await update.message.reply_text(
                "❌ پروژه‌ای با این نام قبلاً ثبت شده است (حتی اگر خاتمه‌یافته باشد).\n"
                "نام دیگری وارد کنید:"
            )
            return PROJ_CRUD_NAME

        logger.info("پروژه جدید ثبت شد: id=%d name=%s", project_id, name)

        telegram_id = update.effective_user.id
        await update.message.reply_text(
            f"✅ پروژهٔ «{name}» با موفقیت ثبت شد.",
            reply_markup=main_menu_keyboard(telegram_id),
        )
        return ConversationHandler.END

    except Exception:
        logger.exception("خطا در add_project_name_save")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# ویرایش نام پروژه
# ══════════════════════════════════════════════════════════════════════════════

async def edit_project_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع مکالمهٔ تغییر نام پروژه.
    callback_data: proj_edit:ID
    """
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update, context):
            return ConversationHandler.END

        project_id = int(query.data.split(":")[1])
        project = get_project_by_id(project_id)
        if not project:
            await query.edit_message_text(
                "⚠️ پروژه یافت نشد.", reply_markup=back_to_main_keyboard()
            )
            return ConversationHandler.END

        context.user_data[_KEY_EDIT_ID] = project_id
        await query.edit_message_text(
            f"✏️ نام فعلی: «{project['name']}»\nنام جدید را وارد کنید:"
        )
        return PROJ_CRUD_EDIT_NAME

    except Exception:
        logger.exception("خطا در edit_project_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def edit_project_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام جدید و ذخیرهٔ rename."""
    try:
        project_id = context.user_data.get(_KEY_EDIT_ID)
        if project_id is None:
            await update.message.reply_text("❌ خطای داخلی — دوباره تلاش کنید.")
            return ConversationHandler.END

        name = _validate_project_name(update.message.text)
        if name is None:
            await update.message.reply_text(
                f"❌ نام نامعتبر است. حداکثر {_MAX_NAME_LEN} کاراکتر و غیرخالی وارد کنید:"
            )
            return PROJ_CRUD_EDIT_NAME

        try:
            update_project_name(project_id, name)
        except sqlite3.IntegrityError:
            await update.message.reply_text(
                "❌ پروژه‌ای با این نام قبلاً ثبت شده است.\nنام دیگری وارد کنید:"
            )
            return PROJ_CRUD_EDIT_NAME

        logger.info("نام پروژه تغییر یافت: id=%d -> %s", project_id, name)
        context.user_data.pop(_KEY_EDIT_ID, None)

        project = get_project_by_id(project_id)
        stats = get_project_stats(project_id)
        await update.message.reply_text(
            "✅ نام پروژه با موفقیت تغییر یافت.\n\n" + _format_project_card(project, stats),
            parse_mode="Markdown",
            reply_markup=project_detail_keyboard(project),
        )
        return ConversationHandler.END

    except Exception:
        logger.exception("خطا در edit_project_name_save")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# خاتمهٔ پروژه (soft، قابل بازگشت)
# ══════════════════════════════════════════════════════════════════════════════

async def terminate_project_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    نمایش هشدار و درخواست تأیید قبل از خاتمهٔ پروژه.
    callback_data: proj_term:ID
    """
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update, context):
            return ConversationHandler.END

        project_id = int(query.data.split(":")[1])
        project = get_project_by_id(project_id)
        if not project or not project.get("is_active"):
            await query.edit_message_text(
                "⚠️ پروژه یافت نشد یا قبلاً خاتمه یافته است.",
                reply_markup=back_to_main_keyboard(),
            )
            return ConversationHandler.END

        stats = get_project_stats(project_id)
        context.user_data[_KEY_TERM_ID] = project_id

        await query.edit_message_text(
            f"⚠️ *آیا از خاتمهٔ این پروژه مطمئن هستید؟*\n\n"
            f"📁 {project['name']}\n"
            f"🏢 پیمانکار فعال: {stats['active_contractors']}\n"
            f"📋 صلاحیت فعال: {stats['active_qualifications']}\n\n"
            f"بعد از خاتمه:\n"
            f"• سوابق (پیمانکار/جوشکار/صلاحیت) دست‌نخورده باقی می‌مانند\n"
            f"• ثبت فعالیت جدید در این پروژه برای همه غیرممکن می‌شود\n"
            f"• این عملیات *قابل بازگشت* است (فعال‌سازی مجدد)",
            parse_mode="Markdown",
            reply_markup=confirm_keyboard(
                yes_data=f"proj_term_yes:{project_id}",
                no_data=f"proj:{project_id}",
            ),
        )
        return PROJ_CRUD_CONFIRM_TERM

    except Exception:
        logger.exception("خطا در terminate_project_confirm")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def terminate_project_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    اجرای خاتمهٔ پروژه (soft-delete).
    callback_data: proj_term_yes:ID
    """
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update, context):
            return ConversationHandler.END

        project_id = int(query.data.split(":")[1])
        set_project_inactive(project_id)
        logger.info("پروژه خاتمه یافت (soft): id=%d", project_id)

        context.user_data.pop(_KEY_TERM_ID, None)
        project = get_project_by_id(project_id)
        stats = get_project_stats(project_id)

        await query.edit_message_text(
            "✅ پروژه خاتمه یافت.\n(سوابق حفظ شده و قابل بازگشت است)\n\n"
            + _format_project_card(project, stats),
            parse_mode="Markdown",
            reply_markup=project_detail_keyboard(project),
        )
        return ConversationHandler.END

    except Exception:
        logger.exception("خطا در terminate_project_execute")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# ساخت ConversationHandler
# ══════════════════════════════════════════════════════════════════════════════

def get_project_conversation_handler() -> ConversationHandler:
    """
    ConversationHandler مدیریت پروژه را می‌سازد و برمی‌گرداند.
    در main.py ثبت می‌شود (قبل از CommandHandlerها، طبق ترتیب مستند در
    ARCHITECTURE.md → Handler Registration Order).
    """
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_project_start,          pattern=r"^proj_new$"),
            CallbackQueryHandler(edit_project_start,          pattern=r"^proj_edit:\d+$"),
            CallbackQueryHandler(terminate_project_confirm,   pattern=r"^proj_term:\d+$"),
        ],
        states={
            PROJ_CRUD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_project_name_save),
            ],
            PROJ_CRUD_EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_project_name_save),
            ],
            PROJ_CRUD_CONFIRM_TERM: [
                CallbackQueryHandler(terminate_project_execute, pattern=r"^proj_term_yes:\d+$"),
                CallbackQueryHandler(project_detail_callback,   pattern=r"^proj:\d+$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", _cancel_project_conv),
            CommandHandler("start",  _cancel_project_conv),
            CallbackQueryHandler(main_menu_callback_fallback, pattern=r"^menu:main$"),
        ],
        per_message=False,  # مطابق CONTRACTS.md
        name="project_crud",
        persistent=False,
    )


async def _cancel_project_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """لغو مکالمهٔ پروژه و بازگشت به منوی اصلی."""
    context.user_data.pop(_KEY_EDIT_ID, None)
    context.user_data.pop(_KEY_TERM_ID, None)

    telegram_id = update.effective_user.id
    if update.message:
        await update.message.reply_text(
            "❌ عملیات لغو شد.",
            reply_markup=main_menu_keyboard(telegram_id),
        )
    return ConversationHandler.END


async def main_menu_callback_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fallback برای بازگشت به منو از داخل مکالمهٔ پروژه."""
    query = update.callback_query
    await query.answer()
    telegram_id = update.effective_user.id
    await query.edit_message_text(
        "🏠 منوی اصلی:",
        reply_markup=main_menu_keyboard(telegram_id),
    )
    return ConversationHandler.END


def get_project_plain_handlers() -> list:
    """
    هندلرهای ساده (غیر-conversation) مربوط به پروژه.
    برای ثبت در main.py.
    """
    return [
        CallbackQueryHandler(show_projects_menu,          pattern=r"^admin:projects$"),
        CallbackQueryHandler(project_detail_callback,      pattern=r"^proj:\d+$"),
        CallbackQueryHandler(reactivate_project_callback,  pattern=r"^proj_reactivate:\d+$"),
    ]
