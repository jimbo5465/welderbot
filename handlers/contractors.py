"""
ماژول contractors — مدیریت رابطهٔ پروژه⇆پیمانکار (فاز ۱۰).

قوانین قفل‌شده:
  - افزودن/الحاق مجدد پیمانکار به پروژه: سطح ۱ (هر پروژه) و سطح ۲ (فقط پروژهٔ خودش)
  - ویرایش نام سراسری پیمانکار (contractors.name): فقط سطح ۱
    (چون این تغییر روی همهٔ پروژه‌های آن پیمانکار اثر می‌گذارد)
  - ویرایش label (نمایش محلی در یک پروژه): سطح ۱ و سطح ۲ (پروژهٔ خودش)
  - خاتمهٔ لینک: سطح ۱ مستقیم؛ سطح ۲ فقط درخواست (تأیید سطح ۱ لازم است)
  - الحاق مجدد بعد از خاتمه: سطح ۱ و سطح ۲، بدون نیاز به تأیید
  - رد یک درخواست: سطح ۱، همراه با دلیل، رابطه به active برمی‌گردد

⚠️ نکات ادغام:
  1. فرض شده `can_manage_contractors(telegram_id, project_id) -> bool` و
     `can_manage_projects(telegram_id) -> bool` در handlers/auth.py موجودند
     (طبق CONTRACTS.md فاز ۸). اگر امضا فرق دارد، فقط _guard_* پایین را اصلاح کنید.
  2. فرض شده config.ADMIN_IDS فهرستی از telegram_id های سطح ۱ است و
     chat_id کاربر برابر telegram_id اوست (فرض رایج در پروژه‌های موجود).
  3. توابع کیبورد در contractors_keyboards_ADD_TO_keyboards_py.py هستند —
     باید به handlers/keyboards.py منتقل شوند.
"""

from __future__ import annotations

import logging
import sqlite3

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

import config
from db.models import (
    get_contractor_by_id,
    get_contractor_by_name,
    add_contractor,
    update_contractor_name,
    link_contractor_to_project,
    get_link_by_id,
    list_contractor_links_by_project,
    update_link_label,
    terminate_link_direct,
    request_terminate_link,
    approve_terminate_link,
    reject_terminate_link,
    get_project_by_id,
)
from handlers.auth import require_auth, can_manage_projects, can_manage_contractors
from handlers.keyboards import back_to_main_keyboard, main_menu_keyboard, confirm_keyboard

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# state ها
# ══════════════════════════════════════════════════════════════════════════════

(
    CTR_NAME,           # نام پیمانکار جدید هنگام افزودن
    CTR_LABEL,          # برچسب اختیاری (افزودن یا الحاق مجدد)
    CTR_LABEL_EDIT,     # ویرایش برچسب یک لینک موجود
    CTR_RENAME,         # ویرایش نام سراسری پیمانکار (فقط سطح ۱)
    CTR_REJECT_REASON,  # دلیل رد درخواست خاتمه (فقط سطح ۱)
) = range(5)

_KEY_PROJECT_ID = "ctr_project_id"
_KEY_CONTRACTOR_ID = "ctr_contractor_id"
_KEY_LINK_ID = "ctr_link_id"

_MAX_NAME_LEN = 100
_MAX_LABEL_LEN = 60

_STATUS_ICON = {
    "active": "🟢",
    "pending_termination": "🟡",
    "terminated": "🔴",
}
_STATUS_FA = {
    "active": "فعال",
    "pending_termination": "در انتظار تأیید خاتمه",
    "terminated": "خاتمه‌یافته",
}


# ══════════════════════════════════════════════════════════════════════════════
# کمکی
# ══════════════════════════════════════════════════════════════════════════════

def _clean_text(text: str, max_len: int) -> str | None:
    t = (text or "").strip()
    if not t or len(t) > max_len:
        return None
    return t


async def _guard_can_manage(update: Update, project_id: int) -> bool:
    """سطح ۱ (هر پروژه) یا سطح ۲ (فقط پروژهٔ خودش) — وگرنه رد."""
    telegram_id = update.effective_user.id
    if can_manage_contractors(telegram_id, project_id):
        return True
    if update.callback_query:
        await update.callback_query.answer("⛔ دسترسی ندارید.", show_alert=True)
    elif update.message:
        await update.message.reply_text("⛔ دسترسی ندارید.")
    return False


async def _guard_level1(update: Update) -> bool:
    telegram_id = update.effective_user.id
    if can_manage_projects(telegram_id):
        return True
    if update.callback_query:
        await update.callback_query.answer("⛔ فقط مدیر سراسری.", show_alert=True)
    elif update.message:
        await update.message.reply_text("⛔ فقط مدیر سراسری.")
    return False


def _link_line(link: dict) -> str:
    icon = _STATUS_ICON.get(link["status"], "⚪")
    label_part = f" ({link['label']})" if link.get("label") else ""
    return f"{icon} {link['contractor_name']}{label_part}"


def _link_card(link: dict) -> str:
    lines = [
        f"🏢 *{link['contractor_name']}*",
        f"وضعیت: {_STATUS_FA.get(link['status'], link['status'])}",
    ]
    if link.get("label"):
        lines.append(f"برچسب: {link['label']}")
    if link["status"] == "terminated" and link.get("terminated_at"):
        lines.append(f"تاریخ خاتمه: {link['terminated_at']}")
    if link["status"] == "pending_termination":
        lines.append("⏳ در انتظار تأیید مدیر سراسری")
    if link.get("reject_reason"):
        lines.append(f"⚠️ آخرین درخواست خاتمه رد شد: {link['reject_reason']}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# فهرست پیمانکاران یک پروژه
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def show_contractors_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    callback_data: ctr_list:<project_id>
    فهرست همهٔ لینک‌ها (فعال/در انتظار/خاتمه‌یافته) برای یک پروژه.
    """
    try:
        query = update.callback_query
        await query.answer()

        project_id = int(query.data.split(":")[1])
        if not await _guard_can_manage(update, project_id):
            return

        project = get_project_by_id(project_id)
        if not project:
            await query.edit_message_text("⚠️ پروژه یافت نشد.", reply_markup=back_to_main_keyboard())
            return

        links = list_contractor_links_by_project(project_id)

        rows = [
            [InlineKeyboardButton(_link_line(l), callback_data=f"ctr_detail:{l['id']}")]
            for l in links
        ]
        rows.append([InlineKeyboardButton("➕ افزودن پیمانکار", callback_data=f"ctr_add:{project_id}")])
        rows.append([InlineKeyboardButton("⬅️ بازگشت به پروژه", callback_data=f"proj:{project_id}")])

        text = f"🏢 پیمانکاران پروژهٔ «{project['name']}»:" if links else \
               f"⚠️ هنوز هیچ پیمانکاری به پروژهٔ «{project['name']}» لینک نشده."

        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows))

    except Exception:
        logger.exception("خطا در show_contractors_menu")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


@require_auth
async def contractor_link_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    callback_data: ctr_detail:<link_id>
    جزئیات یک لینک + دکمه‌های عملیاتی متناسب با وضعیت و سطح کاربر.
    """
    try:
        query = update.callback_query
        await query.answer()

        link_id = int(query.data.split(":")[1])
        link = get_link_by_id(link_id)
        if not link:
            await query.edit_message_text("⚠️ رکورد یافت نشد.", reply_markup=back_to_main_keyboard())
            return

        if not await _guard_can_manage(update, link["project_id"]):
            return

        telegram_id = update.effective_user.id
        is_level1 = can_manage_projects(telegram_id)

        rows = []
        if link["status"] == "active":
            rows.append([InlineKeyboardButton("🏷️ ویرایش برچسب", callback_data=f"ctr_label_edit:{link_id}")])
            if is_level1:
                rows.append([InlineKeyboardButton("✏️ ویرایش نام سراسری پیمانکار", callback_data=f"ctr_rename:{link_id}")])
            rows.append([InlineKeyboardButton("⛔ خاتمهٔ همکاری در این پروژه", callback_data=f"ctr_term_ask:{link_id}")])
        elif link["status"] == "pending_termination" and is_level1:
            rows.append([InlineKeyboardButton("✅ تأیید خاتمه", callback_data=f"ctr_approve:{link_id}")])
            rows.append([InlineKeyboardButton("❌ رد درخواست", callback_data=f"ctr_reject_start:{link_id}")])
        elif link["status"] == "terminated":
            rows.append([InlineKeyboardButton("♻️ الحاق مجدد", callback_data=f"ctr_relink:{link['project_id']}:{link['contractor_id']}")])

        rows.append([InlineKeyboardButton("⬅️ بازگشت به فهرست", callback_data=f"ctr_list:{link['project_id']}")])

        await query.edit_message_text(
            _link_card(link), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows)
        )

    except Exception:
        logger.exception("خطا در contractor_link_detail")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


# ══════════════════════════════════════════════════════════════════════════════
# افزودن پیمانکار (جدید یا موجود) به پروژه
# ══════════════════════════════════════════════════════════════════════════════

async def add_contractor_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ctr_add:<project_id>"""
    try:
        query = update.callback_query
        await query.answer()

        project_id = int(query.data.split(":")[1])
        if not await _guard_can_manage(update, project_id):
            return ConversationHandler.END

        context.user_data[_KEY_PROJECT_ID] = project_id
        await query.edit_message_text(
            "🏢 نام پیمانکار را وارد کنید.\n"
            "(اگر پیمانکاری با این نام قبلاً در پروژهٔ دیگری ثبت شده، "
            "به‌جای ساخت پیمانکار جدید همان را به این پروژه لینک می‌کنیم.)"
        )
        return CTR_NAME

    except Exception:
        logger.exception("خطا در add_contractor_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def add_contractor_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام؛ تصمیم بین ساخت پیمانکار جدید یا لینک به پیمانکار موجود."""
    try:
        name = _clean_text(update.message.text, _MAX_NAME_LEN)
        if name is None:
            await update.message.reply_text(f"❌ نام نامعتبر است (حداکثر {_MAX_NAME_LEN} کاراکتر). دوباره وارد کنید:")
            return CTR_NAME

        existing = get_contractor_by_name(name)
        if existing:
            contractor_id = existing["id"]
            note = "ℹ️ پیمانکاری با این نام از قبل ثبت شده — همان به این پروژه لینک می‌شود.\n\n"
        else:
            contractor_id = add_contractor(name)
            note = ""

        context.user_data[_KEY_CONTRACTOR_ID] = contractor_id

        skip_kb = InlineKeyboardMarkup([[InlineKeyboardButton("➡️ رد کردن (بدون برچسب)", callback_data="ctr_skip_label")]])
        await update.message.reply_text(
            note + "🏷️ برچسب اختیاری برای این پروژه وارد کنید (مثلاً «فاز ۲»)، یا رد کنید:",
            reply_markup=skip_kb,
        )
        return CTR_LABEL

    except Exception:
        logger.exception("خطا در add_contractor_name_received")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


async def _finalize_link(update: Update, context: ContextTypes.DEFAULT_TYPE, label: str | None) -> int:
    """مشترک بین ثبت متن برچسب و زدن دکمهٔ رد کردن — لینک را نهایی می‌کند."""
    project_id = context.user_data.get(_KEY_PROJECT_ID)
    contractor_id = context.user_data.get(_KEY_CONTRACTOR_ID)
    telegram_id = update.effective_user.id

    try:
        link_id = link_contractor_to_project(project_id, contractor_id, telegram_id, label)
    except sqlite3.IntegrityError:
        msg = "❌ این پیمانکار از قبل به‌صورت فعال به این پروژه لینک است."
        if update.callback_query:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END

    logger.info("پیمانکار لینک شد: link_id=%d project=%d contractor=%d", link_id, project_id, contractor_id)
    context.user_data.pop(_KEY_PROJECT_ID, None)
    context.user_data.pop(_KEY_CONTRACTOR_ID, None)

    link = get_link_by_id(link_id)
    text = "✅ پیمانکار با موفقیت به پروژه لینک شد.\n\n" + _link_card(link)
    rows = [[InlineKeyboardButton("⬅️ بازگشت به فهرست", callback_data=f"ctr_list:{project_id}")]]

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))
    return ConversationHandler.END


async def add_contractor_label_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    label = _clean_text(update.message.text, _MAX_LABEL_LEN)
    if label is None:
        await update.message.reply_text(f"❌ برچسب نامعتبر است (حداکثر {_MAX_LABEL_LEN} کاراکتر). دوباره وارد کنید:")
        return CTR_LABEL
    return await _finalize_link(update, context, label)


async def add_contractor_label_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    return await _finalize_link(update, context, None)


# ══════════════════════════════════════════════════════════════════════════════
# الحاق مجدد پیمانکار خاتمه‌یافته (مستقیم، بدون تأیید)
# ══════════════════════════════════════════════════════════════════════════════

async def relink_contractor_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ctr_relink:<project_id>:<contractor_id>"""
    try:
        query = update.callback_query
        await query.answer()

        _, project_id_s, contractor_id_s = query.data.split(":")
        project_id, contractor_id = int(project_id_s), int(contractor_id_s)

        if not await _guard_can_manage(update, project_id):
            return ConversationHandler.END

        context.user_data[_KEY_PROJECT_ID] = project_id
        context.user_data[_KEY_CONTRACTOR_ID] = contractor_id

        skip_kb = InlineKeyboardMarkup([[InlineKeyboardButton("➡️ رد کردن (بدون برچسب)", callback_data="ctr_skip_label")]])
        await query.edit_message_text(
            "🏷️ برچسب اختیاری برای این الحاق مجدد وارد کنید (مثلاً «الحاقیه»)، یا رد کنید:",
            reply_markup=skip_kb,
        )
        return CTR_LABEL

    except Exception:
        logger.exception("خطا در relink_contractor_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# ویرایش برچسب یک لینک موجود
# ══════════════════════════════════════════════════════════════════════════════

async def edit_label_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ctr_label_edit:<link_id>"""
    try:
        query = update.callback_query
        await query.answer()

        link_id = int(query.data.split(":")[1])
        link = get_link_by_id(link_id)
        if not link:
            await query.edit_message_text("⚠️ رکورد یافت نشد.", reply_markup=back_to_main_keyboard())
            return ConversationHandler.END

        if not await _guard_can_manage(update, link["project_id"]):
            return ConversationHandler.END

        context.user_data[_KEY_LINK_ID] = link_id
        await query.edit_message_text(f"🏷️ برچسب فعلی: «{link.get('label') or '—'}»\nبرچسب جدید را وارد کنید:")
        return CTR_LABEL_EDIT

    except Exception:
        logger.exception("خطا در edit_label_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def edit_label_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link_id = context.user_data.get(_KEY_LINK_ID)
    label = _clean_text(update.message.text, _MAX_LABEL_LEN)
    if label is None:
        await update.message.reply_text(f"❌ برچسب نامعتبر است (حداکثر {_MAX_LABEL_LEN} کاراکتر). دوباره وارد کنید:")
        return CTR_LABEL_EDIT

    update_link_label(link_id, label)
    context.user_data.pop(_KEY_LINK_ID, None)

    link = get_link_by_id(link_id)
    rows = [[InlineKeyboardButton("⬅️ بازگشت", callback_data=f"ctr_detail:{link_id}")]]
    await update.message.reply_text(
        "✅ برچسب به‌روزرسانی شد.\n\n" + _link_card(link),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# ویرایش نام سراسری پیمانکار (فقط سطح ۱)
# ══════════════════════════════════════════════════════════════════════════════

async def rename_contractor_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ctr_rename:<link_id> — از روی جزئیات لینک شروع می‌شود."""
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update):
            return ConversationHandler.END

        link_id = int(query.data.split(":")[1])
        link = get_link_by_id(link_id)
        if not link:
            await query.edit_message_text("⚠️ رکورد یافت نشد.", reply_markup=back_to_main_keyboard())
            return ConversationHandler.END

        context.user_data[_KEY_CONTRACTOR_ID] = link["contractor_id"]
        context.user_data[_KEY_LINK_ID] = link_id
        await query.edit_message_text(
            f"✏️ نام سراسری فعلی: «{link['contractor_name']}»\n"
            f"⚠️ این تغییر در همهٔ پروژه‌هایی که این پیمانکار در آن‌ها فعال است دیده می‌شود.\n"
            f"نام جدید را وارد کنید:"
        )
        return CTR_RENAME

    except Exception:
        logger.exception("خطا در rename_contractor_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def rename_contractor_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contractor_id = context.user_data.get(_KEY_CONTRACTOR_ID)
    link_id = context.user_data.get(_KEY_LINK_ID)

    name = _clean_text(update.message.text, _MAX_NAME_LEN)
    if name is None:
        await update.message.reply_text(f"❌ نام نامعتبر است (حداکثر {_MAX_NAME_LEN} کاراکتر). دوباره وارد کنید:")
        return CTR_RENAME

    try:
        update_contractor_name(contractor_id, name)
    except sqlite3.IntegrityError:
        await update.message.reply_text("❌ پیمانکاری با این نام قبلاً ثبت شده. نام دیگری وارد کنید:")
        return CTR_RENAME

    context.user_data.pop(_KEY_CONTRACTOR_ID, None)
    context.user_data.pop(_KEY_LINK_ID, None)

    link = get_link_by_id(link_id)
    rows = [[InlineKeyboardButton("⬅️ بازگشت", callback_data=f"ctr_detail:{link_id}")]]
    await update.message.reply_text(
        "✅ نام پیمانکار به‌روزرسانی شد.\n\n" + _link_card(link),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# خاتمهٔ همکاری (مستقیم برای سطح ۱، درخواست/تأیید برای سطح ۲)
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def terminate_link_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data: ctr_term_ask:<link_id> — تأیید محلی قبل از هر اقدامی."""
    try:
        query = update.callback_query
        await query.answer()

        link_id = int(query.data.split(":")[1])
        link = get_link_by_id(link_id)
        if not link or link["status"] != "active":
            await query.edit_message_text("⚠️ این رابطه در وضعیت فعال نیست.", reply_markup=back_to_main_keyboard())
            return

        if not await _guard_can_manage(update, link["project_id"]):
            return

        telegram_id = update.effective_user.id
        is_level1 = can_manage_projects(telegram_id)

        warning = (
            "⚠️ *آیا از خاتمهٔ همکاری این پیمانکار در این پروژه مطمئن هستید؟*\n\n"
            f"🏢 {link['contractor_name']}\n"
            f"📁 {link['project_name']}\n\n"
        )
        if is_level1:
            warning += "این عملیات فوری اجرا می‌شود."
        else:
            warning += "این درخواست برای تأیید مدیر سراسری ارسال می‌شود و قابل لغو نیست."

        await query.edit_message_text(
            warning,
            parse_mode="Markdown",
            reply_markup=confirm_keyboard(
                yes_data=f"ctr_term_yes:{link_id}",
                no_data=f"ctr_detail:{link_id}",
            ),
        )

    except Exception:
        logger.exception("خطا در terminate_link_ask")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


@require_auth
async def terminate_link_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data: ctr_term_yes:<link_id>"""
    try:
        query = update.callback_query
        await query.answer()

        link_id = int(query.data.split(":")[1])
        link = get_link_by_id(link_id)
        if not link or link["status"] != "active":
            await query.edit_message_text("⚠️ این رابطه دیگر در وضعیت فعال نیست.", reply_markup=back_to_main_keyboard())
            return

        if not await _guard_can_manage(update, link["project_id"]):
            return

        telegram_id = update.effective_user.id

        if can_manage_projects(telegram_id):
            terminate_link_direct(link_id, telegram_id)
            link = get_link_by_id(link_id)
            rows = [[InlineKeyboardButton("⬅️ بازگشت به فهرست", callback_data=f"ctr_list:{link['project_id']}")]]
            await query.edit_message_text(
                "✅ همکاری خاتمه یافت.\n\n" + _link_card(link),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(rows),
            )
        else:
            request_terminate_link(link_id, telegram_id)
            link = get_link_by_id(link_id)
            rows = [[InlineKeyboardButton("⬅️ بازگشت به فهرست", callback_data=f"ctr_list:{link['project_id']}")]]
            await query.edit_message_text(
                "📨 درخواست خاتمه ارسال شد و در انتظار تأیید مدیر سراسری است.\n\n" + _link_card(link),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(rows),
            )

            # اطلاع‌رسانی فوری به همهٔ ادمین‌های سراسری
            approve_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأیید خاتمه", callback_data=f"ctr_approve:{link_id}")],
                [InlineKeyboardButton("❌ رد درخواست", callback_data=f"ctr_reject_start:{link_id}")],
            ])
            for admin_id in config.ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=(
                            "📨 *درخواست خاتمهٔ همکاری پیمانکار*\n\n"
                            f"🏢 {link['contractor_name']}\n"
                            f"📁 {link['project_name']}"
                        ),
                        parse_mode="Markdown",
                        reply_markup=approve_kb,
                    )
                except Exception:
                    logger.exception("ارسال اطلاع‌رسانی به ادمین %s ناموفق بود", admin_id)

    except Exception:
        logger.exception("خطا در terminate_link_execute")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


@require_auth
async def approve_termination(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """callback_data: ctr_approve:<link_id> — فقط سطح ۱."""
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update):
            return

        link_id = int(query.data.split(":")[1])
        link = get_link_by_id(link_id)
        if not link or link["status"] != "pending_termination":
            await query.edit_message_text("⚠️ این درخواست دیگر معتبر نیست.")
            return

        telegram_id = update.effective_user.id
        approve_terminate_link(link_id, telegram_id)
        link = get_link_by_id(link_id)

        await query.edit_message_text("✅ خاتمه تأیید شد.\n\n" + _link_card(link), parse_mode="Markdown")

        if link.get("terminated_by") and link.get("termination_requested_by"):
            try:
                await context.bot.send_message(
                    chat_id=link["termination_requested_by"],
                    text=f"✅ درخواست خاتمهٔ همکاری «{link['contractor_name']}» در «{link['project_name']}» تأیید شد.",
                )
            except Exception:
                logger.exception("اطلاع‌رسانی نتیجه به درخواست‌دهنده ناموفق بود")

    except Exception:
        logger.exception("خطا در approve_termination")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


async def reject_termination_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ctr_reject_start:<link_id> — فقط سطح ۱."""
    try:
        query = update.callback_query
        await query.answer()

        if not await _guard_level1(update):
            return ConversationHandler.END

        link_id = int(query.data.split(":")[1])
        link = get_link_by_id(link_id)
        if not link or link["status"] != "pending_termination":
            await query.edit_message_text("⚠️ این درخواست دیگر معتبر نیست.")
            return ConversationHandler.END

        context.user_data[_KEY_LINK_ID] = link_id
        await query.edit_message_text("❌ دلیل رد درخواست را وارد کنید:")
        return CTR_REJECT_REASON

    except Exception:
        logger.exception("خطا در reject_termination_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def reject_termination_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link_id = context.user_data.get(_KEY_LINK_ID)
    reason = _clean_text(update.message.text, 300)
    if reason is None:
        await update.message.reply_text("❌ دلیل نامعتبر است. دوباره وارد کنید:")
        return CTR_REJECT_REASON

    link_before = get_link_by_id(link_id)
    reject_terminate_link(link_id, reason)
    context.user_data.pop(_KEY_LINK_ID, None)

    link = get_link_by_id(link_id)
    await update.message.reply_text("✅ درخواست رد شد و رابطه دوباره فعال است.\n\n" + _link_card(link), parse_mode="Markdown")

    if link_before and link_before.get("termination_requested_by"):
        try:
            await context.bot.send_message(
                chat_id=link_before["termination_requested_by"],
                text=(
                    f"❌ درخواست خاتمهٔ همکاری «{link['contractor_name']}» در «{link['project_name']}» رد شد.\n"
                    f"دلیل: {reason}"
                ),
            )
        except Exception:
            logger.exception("اطلاع‌رسانی رد درخواست به درخواست‌دهنده ناموفق بود")

    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# این تابع را به handlers/contractors.py اضافه کنید (قبل از بخش
# «ساخت ConversationHandler و هندلرهای ساده»، یا هرجای مناسب دیگر در فایل).
#
# دلیل نیاز: دکمهٔ «⚙️ مدیریت پیمانکاران» در منوی اصلی (از فاز ۸، از قبل در
# main_menu_keyboard وجود داشت) به callback_data="admin:contractors" می‌رود،
# اما تا این لحظه هیچ handler ای این pattern را نمی‌شناخت. این تابع همان
# نقطهٔ ورود گمشده را پر می‌کند: فهرست پروژه‌ها را نشان می‌دهد، با کلیک روی
# هرکدام مستقیم به فهرست پیمانکاران همان پروژه می‌رود (ctr_list:<project_id>) —
# برخلاف admin:projects که به جزئیات پروژه (proj:<project_id>) می‌رود.
#
# ⚠️ فقط سطح ۱: چون در حال حاضر این تابع از can_manage_projects استفاده
# می‌کند (همان گیت admin:projects). سطح ۲ هنوز صفحهٔ «پروژه‌های من» ندارد —
# این یک محدودیت شناخته‌شده است، نه باگ؛ در فاز بعد باید حل شود.
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def contractor_management_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:

    """

    callback_data: admin:contractors

    نقطهٔ ورود از منوی اصلی — فهرست پروژه‌ها را نشان می‌دهد؛ با انتخاب هرکدام

    مستقیم به فهرست پیمانکاران همان پروژه می‌رود.

    فاز ۱۲: سطح ۱ همهٔ پروژه‌ها را می‌بیند؛ سطح ۲ فقط پروژه‌هایی که خودش

    در آن‌ها access_grant سطح ۲ فعال دارد.

    """

    try:

        query = update.callback_query

        await query.answer()



        telegram_id = update.effective_user.id

        from db.models import list_projects

        from handlers.auth import get_my_project_ids, can_manage_projects



        is_level1 = can_manage_projects(telegram_id)

        my_project_ids = get_my_project_ids(telegram_id)



        if not is_level1 and not my_project_ids:

            await query.answer("⛔ دسترسی ندارید.", show_alert=True)

            return



        all_projects = list_projects(active_only=(not is_level1))

        if is_level1:

            projects = all_projects

        else:

            projects = [p for p in all_projects if p["id"] in my_project_ids]



        if not projects:

            await query.edit_message_text(

                "⚠️ هنوز هیچ پروژه‌ای برای شما تعریف نشده.",

                reply_markup=back_to_main_keyboard(),

            )

            return



        rows = []

        for p in projects:

            icon = "📁" if p.get("is_active") else "⛔"

            rows.append([

                InlineKeyboardButton(f"{icon} {p['name']}", callback_data=f"ctr_list:{p['id']}")

            ])

        rows.append([InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu:main")])



        await query.edit_message_text(

            "🏢 پروژه‌ای را برای مشاهدهٔ پیمانکارانش انتخاب کنید:",

            reply_markup=InlineKeyboardMarkup(rows),

        )



    except Exception:

        logger.exception("خطا در contractor_management_entry")

        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


def get_contractor_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_contractor_start,      pattern=r"^ctr_add:\d+$"),
            CallbackQueryHandler(relink_contractor_start,   pattern=r"^ctr_relink:\d+:\d+$"),
            CallbackQueryHandler(edit_label_start,          pattern=r"^ctr_label_edit:\d+$"),
            CallbackQueryHandler(rename_contractor_start,   pattern=r"^ctr_rename:\d+$"),
            CallbackQueryHandler(reject_termination_start,  pattern=r"^ctr_reject_start:\d+$"),
        ],
        states={
            CTR_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_contractor_name_received),
            ],
            CTR_LABEL: [
                CallbackQueryHandler(add_contractor_label_skip, pattern=r"^ctr_skip_label$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_contractor_label_received),
            ],
            CTR_LABEL_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_label_save),
            ],
            CTR_RENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, rename_contractor_save),
            ],
            CTR_REJECT_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, reject_termination_save),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", _cancel_contractor_conv),
            CommandHandler("start", _cancel_contractor_conv),
        ],
        per_message=False,
        name="contractor_lifecycle",
        persistent=False,
    )


async def _cancel_contractor_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in (_KEY_PROJECT_ID, _KEY_CONTRACTOR_ID, _KEY_LINK_ID):
        context.user_data.pop(key, None)
    telegram_id = update.effective_user.id
    if update.message:
        await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=main_menu_keyboard(telegram_id))
    return ConversationHandler.END


def get_contractor_plain_handlers() -> list:
    return [
        CallbackQueryHandler(show_contractors_menu,   pattern=r"^ctr_list:\d+$"),
        CallbackQueryHandler(contractor_link_detail,  pattern=r"^ctr_detail:\d+$"),
        CallbackQueryHandler(terminate_link_ask,      pattern=r"^ctr_term_ask:\d+$"),
        CallbackQueryHandler(terminate_link_execute,  pattern=r"^ctr_term_yes:\d+$"),
        CallbackQueryHandler(approve_termination,     pattern=r"^ctr_approve:\d+$"),
        CallbackQueryHandler(contractor_management_entry, pattern=r"^admin:contractors$"),
    ]

