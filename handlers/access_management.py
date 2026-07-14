"""
ماژول access_management — مکالمه‌ی «معرفی کاربر جدید با سطح دسترسی» (فاز ۸).

جریان:
  admin:users → انتخاب کاربر از pending_users → انتخاب سطح (۱/۲/۳)
    → [اگر سطح ۲ یا ۳] انتخاب پروژه
    → [اگر سطح ۳] انتخاب پیمانکار (فقط پیمانکارهای همان پروژه)
    → تأیید → ذخیره در access_grants

دسترسی به این مکالمه:
  - سطح ۱ (ادمین کل): می‌تواند هر سه سطح را به هر کسی بدهد
  - سطح ۲ (مدیر پیمانکار یک پروژه): فقط می‌تواند سطح ۳ بدهد،
    و فقط برای پیمانکارهای پروژه‌ی خودش
  - سطح ۳ یا بدون دسترسی: اصلاً وارد این مکالمه نمی‌شود
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)

from handlers.auth import (
    get_effective_level,
    can_manage_projects,
    can_grant_level3,
    LEVEL_PROJECT_MANAGER,
    LEVEL_CONTRACTOR_MANAGER,
    LEVEL_OPERATOR,
)
from handlers.keyboards import (
    pending_users_keyboard,
    level_select_keyboard,
    project_select_keyboard,
    grant_contractor_select_keyboard,
    confirm_keyboard,
    back_to_main_keyboard,
    main_menu_keyboard,
)
from db.models import (
    list_pending_users,
    list_projects,
    list_projects_by_contractor,
    list_contractors_by_project,
    add_access_grant,
)

logger = logging.getLogger(__name__)

# ── state ها ─────────────────────────────────────────────────────────────────
SELECT_TARGET_USER, SELECT_LEVEL, SELECT_GRANT_PROJECT, SELECT_GRANT_CONTRACTOR, CONFIRM_GRANT = range(5)


def _d(context: ContextTypes.DEFAULT_TYPE) -> dict:
    """داده‌ی موقت این مکالمه را در user_data نگه می‌دارد."""
    return context.user_data.setdefault("_access_mgmt", {})


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("_access_mgmt", None)


async def _deny_and_end(update: Update) -> int:
    if update.callback_query:
        await update.callback_query.answer("⛔ شما اجازه‌ی مدیریت کاربران را ندارید.", show_alert=True)
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# ورود به مکالمه — callback_data: admin:users
# ══════════════════════════════════════════════════════════════════════════════

async def entry_access_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    tg_user = update.effective_user

    my_level = get_effective_level(tg_user.id)
    if my_level not in (LEVEL_PROJECT_MANAGER, LEVEL_CONTRACTOR_MANAGER):
        return await _deny_and_end(update)

    _clear(context)
    _d(context)["my_telegram_id"] = tg_user.id
    _d(context)["my_level"] = my_level

    users = list_pending_users(exclude_telegram_ids=[tg_user.id])
    if not users:
        await query.edit_message_text(
            "⚠️ هیچ کاربری هنوز /start نزده — کاربر مقصد باید حداقل یک‌بار "
            "ربات را استارت کند تا در این فهرست ظاهر شود.",
            reply_markup=back_to_main_keyboard(),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "👥 *مدیریت دسترسی*\n\nکاربر مورد نظر را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=pending_users_keyboard(users),
    )
    return SELECT_TARGET_USER


# ══════════════════════════════════════════════════════════════════════════════
# مرحله ۱: انتخاب کاربر هدف — callback_data: pend:{telegram_id}
# ══════════════════════════════════════════════════════════════════════════════

async def step_select_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    target_id = int(query.data.split(":")[1])
    _d(context)["target_telegram_id"] = target_id

    allow_level1 = _d(context)["my_level"] == LEVEL_PROJECT_MANAGER
    await query.edit_message_text(
        "سطح دسترسی را انتخاب کنید:",
        reply_markup=level_select_keyboard(allow_level1=allow_level1),
    )
    return SELECT_LEVEL


# ══════════════════════════════════════════════════════════════════════════════
# مرحله ۲: انتخاب سطح — callback_data: lvl:{1|2|3}
# ══════════════════════════════════════════════════════════════════════════════

async def step_select_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    level = int(query.data.split(":")[1])

    # بررسی مجدد مجوز (دفاع در برابر دستکاری callback از سمت کاربر)
    my_level = _d(context)["my_level"]
    if level == LEVEL_PROJECT_MANAGER and my_level != LEVEL_PROJECT_MANAGER:
        return await _deny_and_end(update)
    if level == LEVEL_CONTRACTOR_MANAGER and my_level != LEVEL_PROJECT_MANAGER:
        return await _deny_and_end(update)

    _d(context)["grant_level"] = level

    if level == LEVEL_PROJECT_MANAGER:
        # سراسری — نیازی به انتخاب پروژه/پیمانکار نیست
        return await _render_confirm(update, context)

    # سطح ۲ یا ۳ — باید پروژه انتخاب شود
    if my_level == LEVEL_PROJECT_MANAGER:
        projects = list_projects(active_only=True)
    else:
        # کاربر سطح ۲ فقط می‌تواند در محدوده‌ی پروژه‌ی خودش دسترسی بدهد.
        # چون یک telegram_id ممکن است چند grant سطح۲ در چند پروژه داشته باشد،
        # پروژه‌هایی که او در آن‌ها سطح۲ دارد را نشان می‌دهیم.
        from db.models import get_access_grants_by_telegram
        my_grants = get_access_grants_by_telegram(_d(context)["my_telegram_id"])
        project_ids = [g["project_id"] for g in my_grants if g["level"] == LEVEL_CONTRACTOR_MANAGER]
        all_projects = list_projects(active_only=True)
        projects = [p for p in all_projects if p["id"] in project_ids]

    if not projects:
        await query.edit_message_text(
            "⚠️ هیچ پروژه‌ای در دسترس شما نیست.",
            reply_markup=back_to_main_keyboard(),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "پروژه را انتخاب کنید:",
        reply_markup=project_select_keyboard(projects),
    )
    return SELECT_GRANT_PROJECT


# ══════════════════════════════════════════════════════════════════════════════
# مرحله ۳: انتخاب پروژه — callback_data: gproj:{project_id}
# ══════════════════════════════════════════════════════════════════════════════

async def step_select_grant_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    project_id = int(query.data.split(":")[1])
    _d(context)["grant_project_id"] = project_id

    if _d(context)["grant_level"] == LEVEL_CONTRACTOR_MANAGER:
        return await _render_confirm(update, context)

    # سطح ۳ — باید پیمانکار (محدود به همین پروژه) هم انتخاب شود
    contractors = list_contractors_by_project(project_id, active_only=True)
    if not contractors:
        await query.edit_message_text(
            "⚠️ این پروژه هنوز هیچ پیمانکاری متصل ندارد.\n"
            "ابتدا باید از «⚙️ مدیریت پیمانکاران» یک پیمانکار به این پروژه وصل کنید.",
            reply_markup=back_to_main_keyboard(),
        )
        return ConversationHandler.END

    await query.edit_message_text(
        "پیمانکار را انتخاب کنید:",
        reply_markup=grant_contractor_select_keyboard(contractors),
    )
    return SELECT_GRANT_CONTRACTOR


# ══════════════════════════════════════════════════════════════════════════════
# مرحله ۴: انتخاب پیمانکار — callback_data: gcntr:{contractor_id}
# ══════════════════════════════════════════════════════════════════════════════

async def step_select_grant_contractor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    contractor_id = int(query.data.split(":")[1])
    _d(context)["grant_contractor_id"] = contractor_id
    return await _render_confirm(update, context)


# ══════════════════════════════════════════════════════════════════════════════
# تأیید نهایی
# ══════════════════════════════════════════════════════════════════════════════

async def _render_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    d = _d(context)
    level_names = {1: "مدیر پروژه (سراسری)", 2: "مدیر پیمانکار", 3: "اپراتور"}

    lines = [
        "📋 *تأیید اعطای دسترسی*\n",
        f"👤 کاربر: `{d['target_telegram_id']}`",
        f"🔑 سطح: {level_names[d['grant_level']]}",
    ]
    if d.get("grant_project_id"):
        projects = {p["id"]: p["name"] for p in list_projects(active_only=False)}
        lines.append(f"🏗️ پروژه: {projects.get(d['grant_project_id'], '—')}")
    if d.get("grant_contractor_id"):
        contractors = list_contractors_by_project(d["grant_project_id"], active_only=False)
        c_name = next((c["name"] for c in contractors if c["id"] == d["grant_contractor_id"]), "—")
        lines.append(f"🏢 پیمانکار: {c_name}")

    await query.edit_message_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=confirm_keyboard()
    )
    return CONFIRM_GRANT


async def step_confirm_grant(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":")[1]
    d = _d(context)

    if action != "yes":
        await query.edit_message_text("❌ لغو شد.", reply_markup=back_to_main_keyboard())
        _clear(context)
        return ConversationHandler.END

    try:
        add_access_grant(
            telegram_id=d["target_telegram_id"],
            level=d["grant_level"],
            granted_by=d["my_telegram_id"],
            project_id=d.get("grant_project_id"),
            contractor_id=d.get("grant_contractor_id"),
        )
        await query.edit_message_text("✅ دسترسی با موفقیت ثبت شد.", reply_markup=back_to_main_keyboard())
    except Exception:
        logger.exception("خطا در ثبت access_grant")
        await query.edit_message_text("❌ خطا در ثبت دسترسی. دوباره تلاش کنید.", reply_markup=back_to_main_keyboard())

    _clear(context)
    return ConversationHandler.END


async def cancel_access_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear(context)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ لغو شد.", reply_markup=back_to_main_keyboard())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# ساخت ConversationHandler
# ══════════════════════════════════════════════════════════════════════════════

def get_access_management_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(entry_access_management, pattern=r"^admin:users$"),
        ],
        states={
            SELECT_TARGET_USER: [
                CallbackQueryHandler(step_select_target_user, pattern=r"^pend:"),
            ],
            SELECT_LEVEL: [
                CallbackQueryHandler(step_select_level, pattern=r"^lvl:"),
            ],
            SELECT_GRANT_PROJECT: [
                CallbackQueryHandler(step_select_grant_project, pattern=r"^gproj:"),
            ],
            SELECT_GRANT_CONTRACTOR: [
                CallbackQueryHandler(step_select_grant_contractor, pattern=r"^gcntr:"),
            ],
            CONFIRM_GRANT: [
                CallbackQueryHandler(step_confirm_grant, pattern=r"^confirm:"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_access_management, pattern=r"^menu:main$"),
        ],
        per_message=False,
    )
