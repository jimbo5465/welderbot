"""
ماژول ncr — ثبت گزارش عدم انطباق (NCR) از طریق تلگرام (فاز NCR).

فلوی مکالمه:
    پروژه ← پیمانکار ← گزارش‌دهنده (نام/سمت) ← عملیات ← دیسیپلین
    ← جزیره/واحد/نقشه (اختیاری) ← شرح عدم انطباق
    ← عکس‌ها (اختیاری، تا دکمهٔ «پایان») ← علت ← راهکار ← تأیید HSE
    ← تجهیزات (اختیاری) ← تاریخ ← پیش‌نمایش ← ثبت نهایی
        (شماره‌دهی خودکار + ساخت Excel + ارسال فایل به کاربر)

قوانین قفل‌شده:
  - هر سطح (۱/۲/۳) فقط در scope خودش پروژه/پیمانکار انتخاب می‌کند
    (همان helpers های حلقوی handlers/auth.py).
  - گزارش در حالت draft در همان ابتدای فلوی عکس ذخیره می‌شود؛ در صورت
    انصراف با set_ncr_inactive غیرفعال می‌شود (بدون حذف). ثبت نهایی فقط
    از طریق دکمهٔ تأیید پیش‌نمایش رخ می‌دهد.
  - شمارهٔ NCR فقط در لحظهٔ ثبت نهایی تولید می‌شود (engine/ncr_numbering).
  - فایل Excel فقط از روی رکورد آماده ساخته می‌شود (engine/ncr_excel).

callback_data قفل‌شده: ncr:new | ncr_proj:<id> | ncr_ctr:<id>
   | ncr_skip:<name> | ncr_op:<value> | ncr_disc:<value>
   | ncr_cause:<value> | ncr_cause_other | ncr_hse:<0|1>
   | ncr_today | ncr_finish
"""

from __future__ import annotations

import logging
import os

import jdatetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
    list_projects,
    get_project_by_id,
    list_contractors_by_project,
    get_contractor_by_id,
    get_user_by_telegram_id,
    add_ncr,
    add_ncr_photo,
    list_ncr_photos,
    submit_ncr,
    set_ncr_inactive,
)
from handlers.auth import require_auth, get_my_project_ids, get_my_contractor_id_for_project
from handlers.keyboards import back_to_main_keyboard, main_menu_keyboard
from utils.dates import validate_jalali_date_str

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# state ها
# ══════════════════════════════════════════════════════════════════════════════

(
    NCR_PROJECT,        # انتخاب پروژه
    NCR_CONTRACTOR,     # انتخاب پیمانکار
    NCR_REPORTER_NAME,  # نام گزارش‌دهنده
    NCR_REPORTER_TITLE, # سمت گزارش‌دهنده (اختیاری)
    NCR_OPERATION,      # نوع عملیات
    NCR_DISCIPLINE,     # دیسیپلین
    NCR_ISLAND,         # جزیره (اختیاری)
    NCR_UNIT,           # واحد (اختیاری)
    NCR_DRAWING,        # شماره نقشه (اختیاری)
    NCR_DESCRIPTION,    # شرح عدم انطباق
    NCR_PHOTOS,         # عکس‌ها (اختیاری)
    NCR_CAUSE,          # علت وقوع (گزینه‌ای)
    NCR_CORRECTIVE,     # راهکار رفع
    NCR_HSE,            # تأیید HSE
    NCR_EQUIPMENT,      # تجهیزات (اختیاری)
    NCR_DATE,           # تاریخ گزارش
    NCR_PREVIEW,        # پیش‌نمایش/تأیید نهایی
) = range(17)

_KEY_NCR_ID = "ncr_id"
_KEY_PROJECT_ID = "ncr_project_id"
_KEY_CONTRACTOR_ID = "ncr_contractor_id"

_MAX_TEXT = 2000
_MAX_DESC = 2000

_STATUS_ICON = {"draft": "📝", "submitted": "✅"}


# ══════════════════════════════════════════════════════════════════════════════
# کمکی
# ══════════════════════════════════════════════════════════════════════════════

def _clean_text(value: str | None, max_len: int) -> str | None:
    t = (value or "").strip()
    if not t or len(t) > max_len:
        return None
    return t


def _proj_btn(p: dict) -> InlineKeyboardButton:
    icon = "📁" if p.get("is_active") else "⛔"
    return InlineKeyboardButton(f"{icon} {p['name']}", callback_data=f"ncr_proj:{p['id']}")


def _contractor_buttons(contractors: list[dict]) -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(c["name"], callback_data=f"ncr_ctr:{c['id']}")]
        for c in contractors
    ]


def _op_buttons() -> list[list[InlineKeyboardButton]]:
    from engine.ncr_excel import OPERATION_TYPES
    return [
        [InlineKeyboardButton(v, callback_data=f"ncr_op:{v}")]
        for v in OPERATION_TYPES
    ]


def _disc_buttons() -> list[list[InlineKeyboardButton]]:
    from engine.ncr_excel import DISCIPLINES
    return [
        [InlineKeyboardButton(v, callback_data=f"ncr_disc:{v}")]
        for v in DISCIPLINES
    ]


def _cause_buttons() -> list[list[InlineKeyboardButton]]:
    from engine.ncr_excel import CAUSE_TYPES
    rows = [
        [InlineKeyboardButton(v, callback_data=f"ncr_cause:{v}")]
        for v in CAUSE_TYPES
    ]
    return rows


def _skip_keyboard(name: str, label: str = "⏭ رد کردن") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=f"ncr_skip:{name}")]
    ])


async def _get_report(ncr: dict) -> str:
    """کارت خلاصهٔ NCR برای پیش‌نمایش نهایی."""
    from engine.ncr_numbering import project_code
    lines = [
        f"🏗️ *پروژه*: {ncr['project_name']}",
        f"🏢 *پیمانکار*: {ncr['contractor_name']}",
        f"🧑 *گزارش‌دهنده*: {ncr['reporter_name']}"
        + (f" — {ncr['reporter_title']}" if ncr.get("reporter_title") else ""),
        f"🔧 *عملیات*: {ncr['operation_type'] or '—'}",
        f"📐 *دیسیپلین*: {ncr['discipline'] or '—'}",
    ]
    for label, key in [("🏝️ جزیره", "island"), ("🏗️ واحد", "unit"), ("📄 نقشه", "drawing_number")]:
        if ncr.get(key):
            lines.append(f"{label}: {ncr[key]}")
    lines.append(f"📝 *شرح*: {ncr['description'] or '—'}")
    lines.append(f"⚙️ *علت*: {ncr['cause'] or '—'}")
    lines.append(f"🛠️ *عکس‌ها*: {len(list_ncr_photos(ncr['id']))} عکس")
    lines.append(f"🔨 *راهکار*: {ncr['corrective_action'] or '—'}")
    lines.append(f"🦺 *HSE*: {'✅ تأیید شد' if ncr.get('hse_confirmed') == 1 else '❌ بدون تأیید'}")
    if ncr.get("equipment_description"):
        lines.append(f"🔩 *تجهیزات*: {ncr['equipment_description']}")
    lines.append(f"🗓️ *تاریخ*: {ncr['reported_date'] or '—'}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# نقطه ورود — انتخاب پروژه
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def ncr_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    callback_data: ncr:new
    پروژه‌های مجاز کاربر را نشان می‌دهد و شروع طراحی را انجام می‌دهد.
    """
    try:
        query = update.callback_query
        await query.answer()

        telegram_id = update.effective_user.id
        my_ids = get_my_project_ids(telegram_id)

        projects = list_projects(active_only=True)
        if my_ids is not None:
            projects = [p for p in projects if p["id"] in my_ids]

        if not projects:
            await query.edit_message_text(
                "⚠️ هیچ پروژهٔ فعالی برای انتخاب ندارید.",
                reply_markup=back_to_main_keyboard(),
            )
            return ConversationHandler.END

        rows = [[_proj_btn(p)] for p in projects]
        rows.append([InlineKeyboardButton("🏠 منو", callback_data="menu:main")])
        await query.edit_message_text(
            "⚠️ *ثبت گزارش عدم انطباق (NCR)*\n\n"
            "پروژه را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return NCR_PROJECT

    except Exception:
        logger.exception("خطا در ncr_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def ncr_project_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ncr_proj:<project_id> — انتخاب پیمانکار فعال پروژه."""
    try:
        query = update.callback_query
        await query.answer()

        project_id = int(query.data.split(":")[1])
        project = get_project_by_id(project_id)
        if not project:
            await query.edit_message_text("⚠️ پروژه یافت نشد.", reply_markup=back_to_main_keyboard())
            return ConversationHandler.END

        telegram_id = update.effective_user.id
        restricted = get_my_contractor_id_for_project(telegram_id, project_id)

        contractors = list_contractors_by_project(project_id, active_only=True)
        if restricted is not None:
            contractors = [c for c in contractors if c["id"] == restricted]

        if not contractors:
            await query.edit_message_text(
                f"⚠️ پیمانکار فعالی برای «{project['name']}» ندارید.",
                reply_markup=back_to_main_keyboard(),
            )
            return ConversationHandler.END

        context.user_data[_KEY_PROJECT_ID] = project_id
        rows = _contractor_buttons(contractors)
        rows.append([InlineKeyboardButton("🏠 منو", callback_data="menu:main")])
        await query.edit_message_text(
            f"پروژه: *{project['name']}*\n\n🏢 پیمانکار را انتخاب کنید:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return NCR_CONTRACTOR

    except Exception:
        logger.exception("خطا در ncr_project_selected")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def ncr_contractor_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ncr_ctr:<id>"""
    try:
        query = update.callback_query
        await query.answer()

        contractor_id = int(query.data.split(":")[1])
        project_id = context.user_data.get(_KEY_PROJECT_ID)
        contractor = get_contractor_by_id(contractor_id)
        if not contractor or project_id is None:
            await query.edit_message_text("⚠️ پیمانکار یافت نشد.", reply_markup=back_to_main_keyboard())
            return ConversationHandler.END

        restricted = get_my_contractor_id_for_project(update.effective_user.id, project_id)
        if restricted is not None and contractor_id != restricted:
            await query.answer("⛔ دسترسی ندارید.", show_alert=True)
            return ConversationHandler.END

        context.user_data[_KEY_CONTRACTOR_ID] = contractor_id
        await query.edit_message_text(
            "🧑‍🔧 نام و نام خانوادگی گزارش‌دهنده را وارد کنید:"
        )
        return NCR_REPORTER_NAME

    except Exception:
        logger.exception("خطا در ncr_contractor_selected")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def ncr_reporter_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دریافت نام گزارش‌دهنده + سمت (اختیاری)."""
    try:
        name = _clean_text(update.message.text, 100)
        if name is None:
            await update.message.reply_text("❌ نام نامعتبر است. دوباره وارد کنید:")
            return NCR_REPORTER_NAME
        context.user_data["ncr_reporter_name"] = name
        await update.message.reply_text(
            "💼 سمت گزارش‌دهنده را وارد کنید (مثلاً «بازرس مکانیک»)، یا رد کنید:",
            reply_markup=_skip_keyboard("title"),
        )
        return NCR_REPORTER_TITLE
    except Exception:
        logger.exception("خطا در ncr_reporter_name")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


async def ncr_reporter_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _clean_text(update.message.text, 100)
    if value is None:
        await update.message.reply_text("❌ سمت نامعتبر است. دوباره وارد کنید:")
        return NCR_REPORTER_TITLE
    context.user_data["ncr_reporter_title"] = value
    await update.message.reply_text("🧱 نوع عملیات را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(_op_buttons()))
    return NCR_OPERATION


async def ncr_reporter_title_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(
        "🧱 نوع عملیات را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(_op_buttons())
    )
    return NCR_OPERATION


async def ncr_operation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ncr_op:<value>"""
    await update.callback_query.answer()
    value = update.callback_query.data.split(":", 1)[1]
    context.user_data["ncr_operation"] = value
    await update.callback_query.edit_message_text(
        "📐 دیسیپلین را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(_disc_buttons())
    )
    return NCR_DISCIPLINE


async def ncr_discipline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ncr_disc:<value>"""
    await update.callback_query.answer()
    value = update.callback_query.data.split(":", 1)[1]
    context.user_data["ncr_discipline"] = value
    await update.callback_query.edit_message_text(
        "🏝️ جزیره (اختیاری):", reply_markup=_skip_keyboard("island")
    )
    return NCR_ISLAND


async def ncr_island(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _clean_text(update.message.text, 60)
    context.user_data["ncr_island"] = value
    await update.message.reply_text("🏗️ واحد (اختیاری):", reply_markup=_skip_keyboard("unit"))
    return NCR_UNIT


async def ncr_unit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _clean_text(update.message.text, 60)
    context.user_data["ncr_unit"] = value
    await update.message.reply_text(
        "🧾 شمارهٔ نقشه/رویژن (اختیاری)، یا رد کنید:",
        reply_markup=_skip_keyboard("drawing"),
    )
    return NCR_DRAWING


async def ncr_drawing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _clean_text(update.message.text, 100)
    context.user_data["ncr_drawing"] = value
    await update.message.reply_text(
        "📝 شرح عدم انطباق را بنویسید:\n"
        "(در صورت نیاز نقشه/تصویر اطلاعات تکمیلی را در مرحلهٔ عکس ضمیمه کنید)"
    )
    return NCR_DESCRIPTION


async def ncr_skip_generic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ncr_skip:<name> — رد کردن فیلد اختیاری جاری."""
    try:
        query = update.callback_query
        await query.answer()
        key = query.data.split(":", 1)[1]

        if key == "title":
            context.user_data["ncr_reporter_title"] = ""
            await query.edit_message_text("🧱 نوع عملیات را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(_op_buttons()))
            return NCR_OPERATION
        if key == "island":
            context.user_data["ncr_island"] = ""
            await query.edit_message_text("🏗️ واحد (اختیاری):", reply_markup=_skip_keyboard("unit"))
            return NCR_UNIT
        if key == "unit":
            context.user_data["ncr_unit"] = ""
            await query.edit_message_text("🧾 شمارهٔ نقشه/رویژن (اختیاری):", reply_markup=_skip_keyboard("drawing"))
            return NCR_DRAWING
        if key == "drawing":
            context.user_data["ncr_drawing"] = ""
            await query.edit_message_text(
                "📝 شرح عدم انطباق را بنویسید:\n"
                "(اطلاعات تکمیلی را می‌توانید با عکس ضمیمه کنید)"
            )
            return NCR_DESCRIPTION
        if key == "photos":
            await _finish_photos(update, context)
            return NCR_CAUSE
        if key == "equipment":
            context.user_data["ncr_equipment"] = ""
            today = jdatetime.date.today().strftime("%Y/%m/%d")
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📅 امروز ({today})", callback_data="ncr_today")]
            ])
            await query.edit_message_text(
                f"🗓️ تاریخ گزارش را وارد کنید (فرمت ۱۴۰۴/۰۵/۱۲).\n"
                f"برای امروز دکمهٔ زیر را بزنید:",
                reply_markup=kb,
            )
            return NCR_DATE
        logger.warning("ncr_skip ناشناخته: %s", key)
        return ConversationHandler.END
    except Exception:
        logger.exception("خطا در ncr_skip_generic")
        return ConversationHandler.END


async def ncr_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    desc = _clean_text(update.message.text, _MAX_DESC)
    if desc is None:
        await update.message.reply_text(f"❌ شرح نامعتبر است (حداکثر {_MAX_DESC} کاراکتر). دوباره بنویسید:")
        return NCR_DESCRIPTION
    context.user_data["ncr_description"] = desc
    return await _open_photos(update, context)


async def _open_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    مرحلهٔ عکس‌ها: پیشِ باز user_data یک فهرست фото ایجاد می‌کند؛
    عکس‌ها را می‌فرستد تا دکمهٔ «پایان عکس‌ها» یا skip.
    """
    photos = context.user_data.setdefault("ncr_photos", [])
    kb = _skip_keyboard("photos", label="📂 پایان عکس‌ها")
    count_text = f" ({len(photos)} عکس ثبت شد)" if photos else ""
    await update.message.reply_text(
        "📸 عکس‌های محلِ عدم انطباق را بفرستید (اختیاری، چندتایی هم می‌توانید).\n"
        f"بعد از اتمام، دکمهٔ «پایان عکس‌ها» را بزنید.{count_text}",
        reply_markup=kb,
    )
    return NCR_PHOTOS


async def ncr_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت عکس — مستقیم داخل کاربر پس‌زمینه ذخیره نمی‌شود؛ current عکس‌ها
    را در یک پوشهٔ pending نگه می‌داریم و در زمان ثبت نهایی (کمی بعد که
    ncr_id مشخص شد) به پوشهٔ نهایی منتقل و در DB ثبت می‌شوند.
    """
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)

        user_dir = os.path.join(config.NCR_PHOTO_PATH, "pending", str(update.effective_user.id))
        os.makedirs(user_dir, exist_ok=True)
        num = len(context.user_data.get("ncr_photos", [])) + 1
        full_path = os.path.join(user_dir, f"{num:03d}.jpg")
        await file.download_to_drive(full_path)

        photos = context.user_data.setdefault("ncr_photos", [])
        photos.append(full_path)

        kb = _skip_keyboard("photos", label="📂 پایان عکس‌ها")
        await update.message.reply_text(
            f"✅ عکس {len(photos)} ذخیره شد. اگر عکس دیگری هست بفرستید، وگرنه «پایان عکس‌ها» را بزنید.",
            reply_markup=kb,
        )
        return NCR_PHOTOS
    except Exception:
        logger.exception("خطا در ذخیره عکس NCR")
        await update.message.reply_text("❌ ذخیره عکس ناموفق بود. دوباره تلاش کنید:")
        return NCR_PHOTOS


async def _finish_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پس از پایان عکس‌ها: دکمهٔ علت وقوعی را نشان می‌دهد."""
    query = update.callback_query
    await query.edit_message_text(
        "❓ علت وقوع عدم انطباق را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(_cause_buttons()),
    )


async def ncr_photos_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ncr_skip:photos — پایان دریافت عکس."""
    try:
        query = update.callback_query
        await query.answer()
        await _finish_photos(update, context)
        return NCR_CAUSE
    except Exception:
        logger.exception("خطا در ncr_photos_done")
        return ConversationHandler.END


async def ncr_cause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ncr_cause:<value>"""
    await update.callback_query.answer()
    value = update.callback_query.data.split(":", 1)[1]
    context.user_data["ncr_cause"] = value
    await update.callback_query.edit_message_text(
        "🔨 راهکار/اقدام اصلاحی برای رفع عدم انطباق را بنویسید:\n"
        "(با در نظر گرفتن موارد HSE)"
    )
    return NCR_CORRECTIVE


async def ncr_corrective(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _clean_text(update.message.text, _MAX_TEXT)
    if value is None:
        await update.message.reply_text(f"❌ راهکار نامعتبر است (حداکثر {_MAX_TEXT} کاراکتر). دوباره بنویسید:")
        return NCR_CORRECTIVE
    context.user_data["ncr_corrective"] = value
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ بله، رعایت شد", callback_data="ncr_hse:1")],
        [InlineKeyboardButton("❌ خیر", callback_data="ncr_hse:0")],
    ])
    await update.message.reply_text("🔰 آیا در راهکار، موارد HSE لحاظ شده است؟", reply_markup=kb)
    return NCR_HSE


async def ncr_hse(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ncr_hse:<0|1>"""
    await update.callback_query.answer()
    value = int(update.callback_query.data.split(":")[1])
    context.user_data["ncr_hse"] = value
    await update.callback_query.edit_message_text(
        "🔩 تجهیزات و ماشین آلات مورد استفاده (اختیاری):",
        reply_markup=_skip_keyboard("equipment"),
    )
    return NCR_EQUIPMENT


async def ncr_equipment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _clean_text(update.message.text, 300)
    context.user_data["ncr_equipment"] = value
    return await _ask_date(update.message, context)


async def _ask_date(msg, context: ContextTypes.DEFAULT_TYPE) -> int:
    today = jdatetime.date.today().strftime("%Y/%m/%d")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📅 امروز ({today})", callback_data="ncr_today")]
    ])
    await msg.reply_text(
        f"🗓️ تاریخ گزارش را وارد کنید (فرمت {today} سال/ماه/روز).\n"
        f"برای امروز دکمهٔ زیر را بزنید:",
        reply_markup=kb,
    )
    return NCR_DATE


async def ncr_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    value = _clean_text(update.message.text, 30)
    if not value:
        await update.message.reply_text("❌ تاریخ خالی است. دوباره وارد کنید:")
        return NCR_DATE
    ok, _err = validate_jalali_date_str(value)
    if not ok:
        await update.message.reply_text("❌ تاریخ نامعتبر است. مثال: ۱۴۰۴/۰۵/۱۲")
        return NCR_DATE
    normalized = value.replace("/", "/") if "/" in value else value.replace("-", "/")
    context.user_data["ncr_date"] = normalized
    return await _save_and_preview(update.message, context)


async def ncr_date_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """callback_data: ncr_today"""
    await update.callback_query.answer()
    today = jdatetime.date.today().strftime("%Y/%m/%d")
    context.user_data["ncr_date"] = today
    msg = update.callback_query.message
    return await _save_and_preview(msg, context)


async def _save_and_preview(msg, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    ذخیرهٔ پیش‌نویس (draft) در DB — در این لحظه ncr_id ساخته می‌شود.
    عکس‌ها را به پوشهٔ نهایی می‌برد، سپس پیش‌نمایش نهایی را نشان می‌دهد.
    """
    try:
        project_id = context.user_data.get(_KEY_PROJECT_ID)
        contractor_id = context.user_data.get(_KEY_CONTRACTOR_ID)
        telegram_id = msg.chat.id if msg.chat else None

        user = get_user_by_telegram_id(telegram_id) if telegram_id else None
        if user is None:
            await msg.reply_text("⛔ حساب شما ثبت نشده است. لطفاً /start بزنید.")
            return ConversationHandler.END

        ncr_id = add_ncr(
            project_id=project_id,
            contractor_id=contractor_id,
            reported_by=user["id"],
            reporter_name=context.user_data.get("ncr_reporter_name") or "—",
            reporter_title=context.user_data.get("ncr_reporter_title") or None,
            island=context.user_data.get("ncr_island") or None,
            unit=context.user_data.get("ncr_unit") or None,
            operation_type=context.user_data.get("ncr_operation") or None,
            discipline=context.user_data.get("ncr_discipline") or None,
            drawing_number=context.user_data.get("ncr_drawing") or None,
            description=context.user_data.get("ncr_description") or None,
            cause=context.user_data.get("ncr_cause") or None,
            corrective_action=context.user_data.get("ncr_corrective") or None,
            hse_confirmed=context.user_data.get("ncr_hse"),
            equipment_description=context.user_data.get("ncr_equipment") or None,
            reported_date=context.user_data.get("ncr_date") or None,
        )
        context.user_data[_KEY_NCR_ID] = ncr_id

        # انتقال عکس‌ها از پوشهٔ موقت به پوشهٔ نهایی + ثبت در DB
        photos = context.user_data.get("ncr_photos") or []
        if photos:
            final_dir = os.path.join(config.NCR_PHOTO_PATH, str(ncr_id))
            os.makedirs(final_dir, exist_ok=True)
            for i, src in enumerate(photos, start=1):
                if not os.path.isfile(src):
                    continue
                dest = os.path.join(final_dir, f"{i:03d}.jpg")
                try:
                    os.replace(src, dest)
                    add_ncr_photo(ncr_id, os.path.join("media", "ncr_photos", str(ncr_id), f"{i:03d}.jpg"))
                except OSError:
                    logger.exception("انتقال عکس ناموفق: %s", src)
            context.user_data["ncr_photos"] = []

        context.user_data["ncr_id_session"] = ncr_id
        await _show_preview(msg, context, ncr_id)
        return NCR_PREVIEW

    except Exception:
        logger.exception("خطا در _save_and_preview")
        await msg.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


async def _show_preview(msg, context: ContextTypes.DEFAULT_TYPE, ncr_id: int) -> None:
    from db.models import get_ncr_by_id
    ncr = get_ncr_by_id(ncr_id)
    if not ncr:
        await msg.reply_text("⚠️ رکورد شما ذخیره نشد.")
        return
    text = "📋 *پیش‌نمایش گزارش NCR*\n\n" + await _get_report(ncr)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و ثبت نهایی", callback_data="ncr_finish")],
        [InlineKeyboardButton("❌ انصراف", callback_data="menu:main")],
    ])
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def ncr_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    callback_data: ncr_finish — ثبت نهایی:
    تولید شماره + ساخت Excel + submit + ارسال فایل.
    """
    try:
        query = update.callback_query
        await query.answer()

        ncr_id = context.user_data.get(_KEY_NCR_ID)
        if not ncr_id:
            await query.edit_message_text("⚠️ گزارش یافت نشد.", reply_markup=back_to_main_keyboard())
            return ConversationHandler.END

        from db.models import get_ncr_by_id
        ncr = get_ncr_by_id(ncr_id)
        if not ncr:
            await query.edit_message_text("⚠️ گزارش یافت نشد.", reply_markup=back_to_main_keyboard())
            return ConversationHandler.END

        from engine.ncr_numbering import generate_ncr_number
        from engine.ncr_excel import build_ncr_excel

        number = generate_ncr_number(ncr["project_id"])
        excel_path = build_ncr_excel(ncr_id, number)
        submit_ncr(ncr_id, number, excel_path)

# پاک‌سازی داده‌های جلسه
        for key in list(context.user_data):
            if key.startswith("ncr_") or key.startswith("_KEY_"):
                context.user_data.pop(key, None)
        context.user_data.pop(_KEY_NCR_ID, None)

        final_text = (
            "✅ *گزارش NCR با موفقیت ثبت شد*\n\n"
            f"🔢 شماره: `{number}`\n"
            f"📁 فایل Excel خروجی همین‌جا ارسال شد.\n\n"
            "برای مشاهدهٔ گزارش‌ها/خروجی‌ها بعداً به ابزارهای مدیریتی مراجعه کنید."
        )
        kb = main_menu_keyboard(update.effective_user.id)
        await query.edit_message_text(final_text, parse_mode="Markdown", reply_markup=kb)

        try:
            with open(excel_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=os.path.basename(excel_path),
                    caption=f"NCR {number}",
                )
        except Exception:
            logger.exception("ارسال فایل NCR ناموفق بود")

        return ConversationHandler.END

    except Exception:
        logger.exception("خطا در ncr_finish")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# انصراف / تمیزسازی
# ══════════════════════════════════════════════════════════════════════════════

async def _cancel_ncr_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    ncr_id = context.user_data.pop(_KEY_NCR_ID, None)
    if ncr_id:
        # پیش‌نویس را غیرفعال می‌کنیم (soft-delete) — بدون حذف از DB
        try:
            set_ncr_inactive(ncr_id)
        except Exception:
            logger.exception("خطا در غیرفعال‌سازی پیش‌نویس NCR")
    # حذف عکس‌های موقت (pending) که هنوز به DB وصل نشده‌اند
    for path in context.user_data.get("ncr_photos", []):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass
    for key in list(context.user_data):
        if key.startswith("ncr_") or key.startswith("_KEY_"):
            context.user_data.pop(key, None)
    telegram_id = update.effective_user.id
    if update.message:
        await update.message.reply_text("❌ عملیات لغو شد.", reply_markup=main_menu_keyboard(telegram_id))
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# ساخت ConversationHandler
# ══════════════════════════════════════════════════════════════════════════════

def get_ncr_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(ncr_start, pattern=r"^ncr:new$"),
        ],
        states={
            NCR_PROJECT: [
                CallbackQueryHandler(ncr_project_selected, pattern=r"^ncr_proj:\d+$"),
            ],
            NCR_CONTRACTOR: [
                CallbackQueryHandler(ncr_contractor_selected, pattern=r"^ncr_ctr:\d+$"),
            ],
            NCR_REPORTER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ncr_reporter_name),
            ],
            NCR_REPORTER_TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ncr_reporter_title),
                CallbackQueryHandler(ncr_reporter_title_skip, pattern=r"^ncr_skip:title$"),
            ],
            NCR_OPERATION: [
                CallbackQueryHandler(ncr_operation, pattern=r"^ncr_op:"),
            ],
            NCR_DISCIPLINE: [
                CallbackQueryHandler(ncr_discipline, pattern=r"^ncr_disc:"),
            ],
            NCR_ISLAND: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ncr_island),
                CallbackQueryHandler(ncr_skip_generic, pattern=r"^ncr_skip:island$"),
            ],
            NCR_UNIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ncr_unit),
                CallbackQueryHandler(ncr_skip_generic, pattern=r"^ncr_skip:unit$"),
            ],
            NCR_DRAWING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ncr_drawing),
                CallbackQueryHandler(ncr_skip_generic, pattern=r"^ncr_skip:drawing$"),
            ],
            NCR_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ncr_description),
            ],
            NCR_PHOTOS: [
                MessageHandler(filters.PHOTO, ncr_photo_received),
                CallbackQueryHandler(ncr_photos_done, pattern=r"^ncr_skip:photos$"),
            ],
            NCR_CAUSE: [
                CallbackQueryHandler(ncr_cause, pattern=r"^ncr_cause:"),
            ],
            NCR_CORRECTIVE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ncr_corrective),
            ],
            NCR_HSE: [
                CallbackQueryHandler(ncr_hse, pattern=r"^ncr_hse:[01]$"),
            ],
            NCR_EQUIPMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ncr_equipment),
                CallbackQueryHandler(ncr_skip_generic, pattern=r"^ncr_skip:equipment$"),
            ],
            NCR_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, ncr_date),
                CallbackQueryHandler(ncr_date_today, pattern=r"^ncr_today$"),
            ],
            NCR_PREVIEW: [
                CallbackQueryHandler(ncr_finish, pattern=r"^ncr_finish$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", _cancel_ncr_conv),
            CommandHandler("start", _cancel_ncr_conv),
        ],
        per_message=False,
        name="ncr_registration",
        persistent=False,
    )