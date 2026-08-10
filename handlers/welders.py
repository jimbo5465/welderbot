"""
ماژول welders — جریان‌های مکالمه CRUD جوشکار.
عملیات: فهرست، نمایش جزئیات، افزودن، ویرایش، حذف نرم.
هرگز hard-delete انجام نمی‌شود — فقط set_welder_inactive().
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from telegram import Update, PhotoSize
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
    add_welder,
    get_welder_by_id,
    get_welder_by_national_id,
    list_welders_by_contractor,
    list_contractors,
    search_welders,
    set_welder_inactive,
    update_welder,
    update_welder_photo,
    list_qualifications_by_welder,
)
from utils.validators import validate_national_id, validate_name
from utils.dates import gregorian_to_jalali, is_expired, qualification_status
from handlers.auth import require_auth, require_admin, get_role, ROLE_ADMIN
from handlers.keyboards import (
    welders_list_keyboard,
    welder_detail_keyboard,
    contractor_select_keyboard,
    confirm_keyboard,
    skip_keyboard,
    welder_edit_fields_keyboard,
    back_to_main_keyboard,
    main_menu_keyboard,
)

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# ثابت‌های حالت مکالمه CRUD جوشکار (مستقل از ۳۰ state ثبت WQT)
# ══════════════════════════════════════════════════════════════════════════════
# این state‌ها برای ConversationHandler مجزای CRUD جوشکاران هستند
# و با state‌های test_registration.py تداخل ندارند.

(
    WLD_CRUD_NATIONAL_ID,    # ورود کد ملی جوشکار جدید
    WLD_CRUD_NAME,           # ورود نام جوشکار
    WLD_CRUD_CONTRACTOR,     # انتخاب پیمانکار
    WLD_CRUD_PHOTO,          # دریافت عکس (اختیاری)
    WLD_CRUD_BIRTH_DATE,     # ورود تاریخ تولد (اختیاری)
    WLD_CRUD_EDIT_FIELD,     # انتخاب فیلد برای ویرایش
    WLD_CRUD_EDIT_NAME,      # ورود نام جدید
    WLD_CRUD_EDIT_CONTRACTOR,# انتخاب پیمانکار جدید
    WLD_CRUD_EDIT_PHOTO,     # دریافت عکس جدید
    WLD_CRUD_EDIT_BDATE,     # ورود تاریخ تولد جدید
    WLD_CRUD_CONFIRM_DELETE, # تأیید حذف
    WLD_CRUD_SEARCH,         # ورود متن جستجو
) = range(12)


# ── کلیدهای context.user_data ─────────────────────────────────────────────────
_KEY_PAGE        = "wld_page"
_KEY_CONTRACTORS = "wld_contractors"
_KEY_NEW_WELDER  = "wld_new"      # dict در حال ساخت برای جوشکار جدید
_KEY_EDIT_ID     = "wld_edit_id"  # id جوشکار در حال ویرایش


# ══════════════════════════════════════════════════════════════════════════════
# توابع کمکی
# ══════════════════════════════════════════════════════════════════════════════

def _format_welder_card(w: dict, quals: list[dict] | None = None) -> str:
    """
    اطلاعات یک جوشکار را به صورت متن فارسی قالب‌بندی می‌کند.
    """
    birth = w.get("birth_date")
    birth_str = gregorian_to_jalali(birth) if birth else "—"

    lines = [
        f"👷 *{w['full_name']}*",
        f"🪪 کد ملی: `{w['national_id']}`",
        f"📅 تاریخ تولد: {birth_str}",
        f"🏢 شناسه پیمانکار: {w['contractor_id']}",
        f"✅ وضعیت: {'فعال' if w.get('is_active') else 'غیرفعال'}",
    ]

    if quals is not None:
        active_quals = [q for q in quals if q.get("is_active")]
        lines.append(f"\n📋 صلاحیت‌های فعال: {len(active_quals)} مورد")
        for q in active_quals[:3]:
            status = qualification_status(q["expiry_date"])
            lines.append(
                f"  • {q['process']} | {q['base_metal_p_no']} | وضعیت: {status}"
            )
        if len(active_quals) > 3:
            lines.append(f"  ... و {len(active_quals) - 3} مورد دیگر")

    return "\n".join(lines)


async def _safe_reply(update: Update, text: str, **kwargs) -> None:
    """ارسال پیام ایمن — هم برای message هم برای callback_query."""
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", **kwargs)
        except Exception:
            await update.callback_query.message.reply_text(text, parse_mode="Markdown", **kwargs)
    elif update.message:
        await update.message.reply_text(text, parse_mode="Markdown", **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# فهرست جوشکاران
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def show_welders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نمایش منوی انتخاب پیمانکار برای فیلتر فهرست جوشکاران.
    callback_data: menu:welders
    """
    try:
        query = update.callback_query
        await query.answer()

        contractors = list_contractors(active_only=True)
        if not contractors:
            await query.edit_message_text(
                "⚠️ هیچ پیمانکاری ثبت نشده است.\nابتدا پیمانکار اضافه کنید.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        context.user_data[_KEY_CONTRACTORS] = contractors
        await query.edit_message_text(
            "🏢 پیمانکار مورد نظر را انتخاب کنید:",
            reply_markup=contractor_select_keyboard(contractors),
        )

    except Exception:
        logger.exception("خطا در show_welders_menu")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


@require_auth
async def show_welders_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نمایش فهرست جوشکاران یک پیمانکار.
    callback_data: cntr:ID
    """
    try:
        query = update.callback_query
        await query.answer()

        contractor_id = int(query.data.split(":")[1])
        context.user_data["wld_contractor_id"] = contractor_id

        welders = list_welders_by_contractor(contractor_id, active_only=True)
        context.user_data["wld_welders"] = welders
        context.user_data[_KEY_PAGE] = 0

        if not welders:
            role = context.user_data.get("role", "operator")
            await query.edit_message_text(
                "⚠️ هیچ جوشکار فعالی برای این پیمانکار یافت نشد.",
                reply_markup=welders_list_keyboard([], page=0),
            )
            return

        await query.edit_message_text(
            f"👷 جوشکاران پیمانکار (تعداد: {len(welders)}):",
            reply_markup=welders_list_keyboard(welders, page=0),
        )

    except Exception:
        logger.exception("خطا در show_welders_list")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


@require_auth
async def welders_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    صفحه‌بندی فهرست جوشکاران.
    callback_data: wldr_page:N
    """
    try:
        query = update.callback_query
        await query.answer()

        page = int(query.data.split(":")[1])
        context.user_data[_KEY_PAGE] = page
        welders = context.user_data.get("wld_welders", [])

        await query.edit_message_text(
            f"👷 جوشکاران (صفحه {page + 1}):",
            reply_markup=welders_list_keyboard(welders, page=page),
        )

    except Exception:
        logger.exception("خطا در welders_page_callback")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


# ══════════════════════════════════════════════════════════════════════════════
# نمایش جزئیات جوشکار
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def welder_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    نمایش جزئیات یک جوشکار.
    callback_data: wldr:ID
    """
    try:
        query = update.callback_query
        await query.answer()

        welder_id = int(query.data.split(":")[1])
        welder = get_welder_by_id(welder_id)

        if not welder or not welder.get("is_active"):
            await query.edit_message_text(
                "⚠️ جوشکار مورد نظر یافت نشد.",
                reply_markup=back_to_main_keyboard(),
            )
            return

        quals = list_qualifications_by_welder(welder_id, active_only=True)
        card  = _format_welder_card(welder, quals)

        tg_user = update.effective_user
        role = context.user_data.get("role") or get_role(tg_user.id)

        await query.edit_message_text(
            card,
            parse_mode="Markdown",
            reply_markup=welder_detail_keyboard(welder_id, role or "operator"),
        )

    except Exception:
        logger.exception("خطا در welder_detail_callback")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)


# ══════════════════════════════════════════════════════════════════════════════
# جستجوی جوشکار
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع جریان جستجوی جوشکار.
    callback_data: menu:search
    """
    try:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "🔍 نام یا کد ملی جوشکار را وارد کنید:\n"
            "(حداقل ۲ کاراکتر)"
        )
        return WLD_CRUD_SEARCH

    except Exception:
        logger.exception("خطا در search_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


@require_auth
async def search_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    اجرای جستجو و نمایش نتایج.
    """
    try:
        query_text = update.message.text.strip()
        if len(query_text) < 2:
            await update.message.reply_text(
                "⚠️ حداقل ۲ کاراکتر وارد کنید:"
            )
            return WLD_CRUD_SEARCH

        results = search_welders(query_text)
        if not results:
            await update.message.reply_text(
                "❌ جوشکاری با این مشخصات یافت نشد.",
                reply_markup=back_to_main_keyboard(),
            )
            return ConversationHandler.END

        context.user_data["wld_welders"] = results
        context.user_data[_KEY_PAGE] = 0

        await update.message.reply_text(
            f"✅ {len(results)} نتیجه یافت شد:",
            reply_markup=welders_list_keyboard(results, page=0),
        )
        return ConversationHandler.END

    except Exception:
        logger.exception("خطا در search_execute")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# افزودن جوشکار جدید — ConversationHandler
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def add_welder_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع جریان افزودن جوشکار.
    callback_data: wldr_new:1
    """
    try:
        query = update.callback_query
        await query.answer()

        # پاکسازی داده قبلی
        context.user_data[_KEY_NEW_WELDER] = {}

        await query.edit_message_text(
            "➕ *افزودن جوشکار جدید*\n\n"
            "📌 مرحله ۱ از ۵\n"
            "کد ملی ۱۰ رقمی جوشکار را وارد کنید:"
        )
        return WLD_CRUD_NATIONAL_ID

    except Exception:
        logger.exception("خطا در add_welder_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


@require_auth
async def add_welder_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت و اعتبارسنجی کد ملی جوشکار.
    """
    try:
        text = update.message.text.strip()

        if not validate_national_id(text):
            await update.message.reply_text(
                "⚠️ کد ملی وارد شده معتبر نیست.\n"
                "کد ملی باید ۱۰ رقم عددی صحیح باشد.\n"
                "لطفاً دوباره وارد کنید:"
            )
            return WLD_CRUD_NATIONAL_ID

        # بررسی تکراری نبودن کد ملی
        existing = get_welder_by_national_id(text)
        if existing and existing.get("is_active"):
            await update.message.reply_text(
                f"⚠️ جوشکاری با کد ملی `{text}` قبلاً ثبت شده است.\n"
                f"نام: *{existing['full_name']}*\n\n"
                "آیا می‌خواهید اطلاعات همین جوشکار را ببینید؟",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup_from_welder(existing["id"]),
            )
            context.user_data.pop(_KEY_NEW_WELDER, None)
            return ConversationHandler.END

        context.user_data[_KEY_NEW_WELDER]["national_id"] = text
        await update.message.reply_text(
            "✅ کد ملی تأیید شد.\n\n"
            "📌 مرحله ۲ از ۵\n"
            "نام و نام خانوادگی جوشکار را به فارسی وارد کنید:"
        )
        return WLD_CRUD_NAME

    except Exception:
        logger.exception("خطا در add_welder_national_id")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


def InlineKeyboardMarkup_from_welder(welder_id: int):
    """keyboard کوچک برای هدایت به صفحه جزئیات جوشکار موجود."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👀 مشاهده جوشکار", callback_data=f"wldr:{welder_id}")],
        [InlineKeyboardButton("🏠 بازگشت به منو",  callback_data="menu:main")],
    ])


@require_auth
async def add_welder_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت و اعتبارسنجی نام جوشکار.
    """
    try:
        text = update.message.text.strip()

        if not validate_name(text):
            await update.message.reply_text(
                "⚠️ نام وارد شده معتبر نیست.\n"
                "نام باید فارسی و حداقل ۲ کاراکتر باشد.\n"
                "لطفاً دوباره وارد کنید:"
            )
            return WLD_CRUD_NAME

        context.user_data[_KEY_NEW_WELDER]["full_name"] = text

        # دریافت فهرست پیمانکاران
        contractors = list_contractors(active_only=True)
        if not contractors:
            await update.message.reply_text(
                "⚠️ هیچ پیمانکاری در سیستم ثبت نشده است.\n"
                "لطفاً ابتدا پیمانکار اضافه کنید.",
                reply_markup=back_to_main_keyboard(),
            )
            return ConversationHandler.END

        context.user_data[_KEY_CONTRACTORS] = contractors
        await update.message.reply_text(
            "📌 مرحله ۳ از ۵\n"
            "پیمانکار این جوشکار را انتخاب کنید:",
            reply_markup=contractor_select_keyboard(contractors),
        )
        return WLD_CRUD_CONTRACTOR

    except Exception:
        logger.exception("خطا در add_welder_name")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


@require_auth
async def add_welder_contractor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت انتخاب پیمانکار.
    callback_data: cntr:ID
    """
    try:
        query = update.callback_query
        await query.answer()

        contractor_id = int(query.data.split(":")[1])
        context.user_data[_KEY_NEW_WELDER]["contractor_id"] = contractor_id

        await query.edit_message_text(
            "📌 مرحله ۴ از ۵\n"
            "عکس جوشکار را ارسال کنید یا از آن صرف‌نظر کنید:",
            reply_markup=skip_keyboard("photo"),
        )
        return WLD_CRUD_PHOTO

    except Exception:
        logger.exception("خطا در add_welder_contractor")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


@require_auth
async def add_welder_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت عکس جوشکار و ذخیره در disk.
    """
    try:
        photo_path = None

        if update.message and update.message.photo:
            # دریافت بزرگ‌ترین اندازه عکس
            photo: PhotoSize = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)

            national_id = context.user_data[_KEY_NEW_WELDER]["national_id"]
            timestamp   = datetime.now().strftime("%Y%m%d%H%M%S")
            filename    = f"{national_id}_{timestamp}.jpg"
            full_path   = os.path.join(config.MEDIA_PATH, filename)

            await file.download_to_drive(full_path)
            photo_path = os.path.join("media", "photos", filename)
            logger.info("عکس جوشکار ذخیره شد: %s", full_path)

        context.user_data[_KEY_NEW_WELDER]["photo_path"] = photo_path

        await (update.message or update.callback_query.message).reply_text(
            "📌 مرحله ۵ از ۵ (اختیاری)\n"
            "تاریخ تولد جوشکار را به فرمت جلالی وارد کنید:\n"
            "مثال: ۱۳۷۰/۰۵/۱۵\n\n"
            "یا برای رد کردن دکمه زیر را بزنید:",
            reply_markup=skip_keyboard("birth_date"),
        )
        return WLD_CRUD_BIRTH_DATE

    except Exception:
        logger.exception("خطا در add_welder_photo")
        if update.message:
            await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


@require_auth
async def add_welder_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    رد کردن مرحله عکس.
    callback_data: skip:photo
    """
    try:
        query = update.callback_query
        await query.answer()
        context.user_data[_KEY_NEW_WELDER]["photo_path"] = None

        await query.edit_message_text(
            "📌 مرحله ۵ از ۵ (اختیاری)\n"
            "تاریخ تولد جوشکار را به فرمت جلالی وارد کنید:\n"
            "مثال: ۱۳۷۰/۰۵/۱۵\n\n"
            "یا برای رد کردن دکمه زیر را بزنید:",
            reply_markup=skip_keyboard("birth_date"),
        )
        return WLD_CRUD_BIRTH_DATE

    except Exception:
        logger.exception("خطا در add_welder_skip_photo")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


@require_auth
async def add_welder_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    دریافت تاریخ تولد و ذخیره نهایی جوشکار.
    """
    try:
        from utils.dates import jalali_to_gregorian, validate_jalali_date_str

        birth_date_gregorian = None

        if update.message:
            text = update.message.text.strip()
            ok, err = validate_jalali_date_str(text)
            if not ok:
                await update.message.reply_text(
                    f"⚠️ {err}\n"
                    "لطفاً دوباره وارد کنید یا از دکمه «رد کردن» استفاده کنید:",
                    reply_markup=skip_keyboard("birth_date"),
                )
                return WLD_CRUD_BIRTH_DATE
            try:
                birth_date_gregorian = jalali_to_gregorian(text)
            except Exception:
                birth_date_gregorian = None

        context.user_data[_KEY_NEW_WELDER]["birth_date"] = birth_date_gregorian
        return await _finalize_add_welder(update, context)

    except Exception:
        logger.exception("خطا در add_welder_birth_date")
        if update.message:
            await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


@require_auth
async def add_welder_skip_birth_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    رد کردن مرحله تاریخ تولد.
    callback_data: skip:birth_date
    """
    try:
        query = update.callback_query
        await query.answer()
        context.user_data[_KEY_NEW_WELDER]["birth_date"] = None
        return await _finalize_add_welder(update, context)

    except Exception:
        logger.exception("خطا در add_welder_skip_birth_date")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


async def _finalize_add_welder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    ذخیره نهایی جوشکار جدید در DB.
    """
    data = context.user_data.get(_KEY_NEW_WELDER, {})

    try:
        new_id = add_welder(
            national_id=data["national_id"],
            full_name=data["full_name"],
            contractor_id=data["contractor_id"],
            photo_path=data.get("photo_path"),
            birth_date=data.get("birth_date"),
        )
        logger.info("جوشکار جدید ثبت شد: id=%d کد_ملی=%s", new_id, data["national_id"])

        role = context.user_data.get("role", "operator")
        success_msg = (
            f"✅ *جوشکار با موفقیت ثبت شد!*\n\n"
            f"👤 نام: {data['full_name']}\n"
            f"🪪 کد ملی: `{data['national_id']}`\n"
            f"🆔 شناسه: {new_id}"
        )

        msg_obj = update.callback_query.message if update.callback_query else update.message
        await msg_obj.reply_text(
            success_msg,
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(role),
        )

        # پاکسازی داده موقت
        context.user_data.pop(_KEY_NEW_WELDER, None)
        return ConversationHandler.END

    except Exception as e:
        logger.exception("خطا در ذخیره جوشکار جدید")
        msg_obj = update.callback_query.message if update.callback_query else update.message
        await msg_obj.reply_text(
            f"❌ خطا در ثبت جوشکار: {str(e)[:100]}",
            reply_markup=back_to_main_keyboard(),
        )
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# ویرایش جوشکار
# ══════════════════════════════════════════════════════════════════════════════

@require_admin
async def edit_welder_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    شروع جریان ویرایش جوشکار — فقط admin.
    callback_data: wldr_edit:ID
    """
    try:
        query = update.callback_query
        await query.answer()

        welder_id = int(query.data.split(":")[1])
        welder    = get_welder_by_id(welder_id)

        if not welder or not welder.get("is_active"):
            await query.edit_message_text(
                "⚠️ جوشکار یافت نشد.",
                reply_markup=back_to_main_keyboard(),
            )
            return ConversationHandler.END

        context.user_data[_KEY_EDIT_ID] = welder_id
        context.user_data["wld_edit_data"] = dict(welder)

        await query.edit_message_text(
            f"✏️ *ویرایش جوشکار: {welder['full_name']}*\n\n"
            "کدام فیلد را می‌خواهید تغییر دهید؟",
            parse_mode="Markdown",
            reply_markup=welder_edit_fields_keyboard(welder_id),
        )
        return WLD_CRUD_EDIT_FIELD

    except Exception:
        logger.exception("خطا در edit_welder_start")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


@require_admin
async def edit_field_name_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """درخواست نام جدید جوشکار."""
    query = update.callback_query
    await query.answer()
    current = context.user_data.get("wld_edit_data", {}).get("full_name", "")
    await query.edit_message_text(
        f"👤 نام فعلی: *{current}*\n\nنام جدید را وارد کنید:",
        parse_mode="Markdown",
    )
    return WLD_CRUD_EDIT_NAME


@require_admin
async def edit_field_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ذخیره نام جدید."""
    try:
        text = update.message.text.strip()
        if not validate_name(text):
            await update.message.reply_text(
                "⚠️ نام معتبر نیست. فقط حروف فارسی و حداقل ۲ کاراکتر:\n"
                "دوباره وارد کنید:"
            )
            return WLD_CRUD_EDIT_NAME

        welder_id  = context.user_data[_KEY_EDIT_ID]
        edit_data  = context.user_data["wld_edit_data"]
        edit_data["full_name"] = text

        update_welder(
            welder_id=welder_id,
            full_name=text,
            contractor_id=edit_data["contractor_id"],
            birth_date=edit_data.get("birth_date"),
        )
        await update.message.reply_text(
            f"✅ نام با موفقیت به *{text}* تغییر یافت.",
            parse_mode="Markdown",
            reply_markup=welder_edit_fields_keyboard(welder_id),
        )
        return WLD_CRUD_EDIT_FIELD

    except Exception:
        logger.exception("خطا در edit_field_name_save")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


@require_admin
async def edit_field_contractor_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """درخواست پیمانکار جدید."""
    query = update.callback_query
    await query.answer()
    contractors = list_contractors(active_only=True)
    context.user_data[_KEY_CONTRACTORS] = contractors
    await query.edit_message_text(
        "🏢 پیمانکار جدید را انتخاب کنید:",
        reply_markup=contractor_select_keyboard(contractors),
    )
    return WLD_CRUD_EDIT_CONTRACTOR


@require_admin
async def edit_field_contractor_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ذخیره پیمانکار جدید."""
    try:
        query = update.callback_query
        await query.answer()

        contractor_id = int(query.data.split(":")[1])
        welder_id     = context.user_data[_KEY_EDIT_ID]
        edit_data     = context.user_data["wld_edit_data"]
        edit_data["contractor_id"] = contractor_id

        update_welder(
            welder_id=welder_id,
            full_name=edit_data["full_name"],
            contractor_id=contractor_id,
            birth_date=edit_data.get("birth_date"),
        )
        await query.edit_message_text(
            "✅ پیمانکار با موفقیت تغییر یافت.",
            reply_markup=welder_edit_fields_keyboard(welder_id),
        )
        return WLD_CRUD_EDIT_FIELD

    except Exception:
        logger.exception("خطا در edit_field_contractor_save")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


@require_admin
async def edit_field_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """درخواست عکس جدید."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🖼 عکس جدید جوشکار را ارسال کنید:")
    return WLD_CRUD_EDIT_PHOTO


@require_admin
async def edit_field_photo_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ذخیره عکس جدید."""
    try:
        welder_id = context.user_data[_KEY_EDIT_ID]
        welder    = context.user_data["wld_edit_data"]

        if update.message and update.message.photo:
            photo    = update.message.photo[-1]
            file     = await context.bot.get_file(photo.file_id)
            filename = f"{welder['national_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
            full_path = os.path.join(config.MEDIA_PATH, filename)
            await file.download_to_drive(full_path)
            photo_path = os.path.join("media", "photos", filename)
            update_welder_photo(welder_id, photo_path)

        await update.message.reply_text(
            "✅ عکس با موفقیت به‌روز شد.",
            reply_markup=welder_edit_fields_keyboard(welder_id),
        )
        return WLD_CRUD_EDIT_FIELD

    except Exception:
        logger.exception("خطا در edit_field_photo_save")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


@require_admin
async def edit_field_bdate_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """درخواست تاریخ تولد جدید."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📅 تاریخ تولد جدید را به فرمت جلالی وارد کنید:\n"
        "مثال: ۱۳۷۰/۰۵/۱۵",
    )
    return WLD_CRUD_EDIT_BDATE


@require_admin
async def edit_field_bdate_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ذخیره تاریخ تولد جدید."""
    try:
        from utils.dates import jalali_to_gregorian, validate_jalali_date_str

        text = update.message.text.strip()
        ok, err = validate_jalali_date_str(text)
        if not ok:
            await update.message.reply_text(
                f"⚠️ {err}\nدوباره وارد کنید:"
            )
            return WLD_CRUD_EDIT_BDATE

        gregorian = jalali_to_gregorian(text)
        welder_id = context.user_data[_KEY_EDIT_ID]
        edit_data = context.user_data["wld_edit_data"]
        edit_data["birth_date"] = gregorian

        update_welder(
            welder_id=welder_id,
            full_name=edit_data["full_name"],
            contractor_id=edit_data["contractor_id"],
            birth_date=gregorian,
        )
        await update.message.reply_text(
            f"✅ تاریخ تولد با موفقیت به {text} تغییر یافت.",
            reply_markup=welder_edit_fields_keyboard(welder_id),
        )
        return WLD_CRUD_EDIT_FIELD

    except Exception:
        logger.exception("خطا در edit_field_bdate_save")
        await update.message.reply_text("❌ خطایی رخ داد.")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# حذف نرم جوشکار
# ══════════════════════════════════════════════════════════════════════════════

@require_admin
async def delete_welder_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    درخواست تأیید قبل از حذف.
    callback_data: wldr_del:ID
    فقط soft-delete — هرگز hard-delete.
    """
    try:
        query = update.callback_query
        await query.answer()

        welder_id = int(query.data.split(":")[1])
        welder    = get_welder_by_id(welder_id)

        if not welder or not welder.get("is_active"):
            await query.edit_message_text(
                "⚠️ جوشکار یافت نشد یا قبلاً حذف شده است.",
                reply_markup=back_to_main_keyboard(),
            )
            return ConversationHandler.END

        context.user_data["wld_delete_id"] = welder_id
        await query.edit_message_text(
            f"⚠️ *آیا مطمئن هستید؟*\n\n"
            f"👤 نام: {welder['full_name']}\n"
            f"🪪 کد ملی: `{welder['national_id']}`\n\n"
            f"این عملیات جوشکار را *غیرفعال* می‌کند (حذف دائمی نیست).",
            parse_mode="Markdown",
            reply_markup=confirm_keyboard(
                yes_data=f"wldr_del_yes:{welder_id}",
                no_data=f"wldr:{welder_id}",
            ),
        )
        return WLD_CRUD_CONFIRM_DELETE

    except Exception:
        logger.exception("خطا در delete_welder_confirm")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


@require_admin
async def delete_welder_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    اجرای حذف نرم (soft-delete) جوشکار.
    callback_data: wldr_del_yes:ID
    فقط set_welder_inactive() — هرگز DELETE SQL.
    """
    try:
        query = update.callback_query
        await query.answer()

        welder_id = int(query.data.split(":")[1])

        # ← حذف نرم: فقط is_active=0
        set_welder_inactive(welder_id)
        logger.info("جوشکار غیرفعال شد (soft-delete): id=%d", welder_id)

        role = context.user_data.get("role", ROLE_ADMIN)
        await query.edit_message_text(
            "✅ جوشکار با موفقیت غیرفعال شد.\n"
            "(رکورد حفظ شده و قابل بازیابی است)",
            reply_markup=main_menu_keyboard(role),
        )
        context.user_data.pop("wld_delete_id", None)
        return ConversationHandler.END

    except Exception:
        logger.exception("خطا در delete_welder_execute")
        await update.callback_query.answer("❌ خطایی رخ داد.", show_alert=True)
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# ساخت ConversationHandler
# ══════════════════════════════════════════════════════════════════════════════

def get_welder_conversation_handler() -> ConversationHandler:
    """
    ConversationHandler اصلی جوشکار را می‌سازد و برمی‌گرداند.
    در main.py ثبت می‌شود.
    """
    return ConversationHandler(
        entry_points=[
            # ورود از دکمه «افزودن جوشکار»
            CallbackQueryHandler(add_welder_start,      pattern=r"^wldr_new:"),
            # ورود از دکمه «ویرایش جوشکار»
            CallbackQueryHandler(edit_welder_start,     pattern=r"^wldr_edit:"),
            # ورود از دکمه «حذف جوشکار»
            CallbackQueryHandler(delete_welder_confirm, pattern=r"^wldr_del:\d+$"),
            # ورود از منوی جستجو
            CallbackQueryHandler(search_start,          pattern=r"^menu:search$"),
        ],
        states={
            # ── افزودن جوشکار ──────────────────────────────────────────
            WLD_CRUD_NATIONAL_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_welder_national_id),
            ],
            WLD_CRUD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_welder_name),
            ],
            WLD_CRUD_CONTRACTOR: [
                CallbackQueryHandler(add_welder_contractor, pattern=r"^cntr:\d+$"),
            ],
            WLD_CRUD_PHOTO: [
                MessageHandler(filters.PHOTO, add_welder_photo),
                CallbackQueryHandler(add_welder_skip_photo, pattern=r"^skip:photo$"),
            ],
            WLD_CRUD_BIRTH_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_welder_birth_date),
                CallbackQueryHandler(add_welder_skip_birth_date, pattern=r"^skip:birth_date$"),
            ],
            # ── ویرایش جوشکار ──────────────────────────────────────────
            WLD_CRUD_EDIT_FIELD: [
                CallbackQueryHandler(edit_field_name_prompt,       pattern=r"^edit:wldr_name:"),
                CallbackQueryHandler(edit_field_contractor_prompt, pattern=r"^edit:wldr_cntr:"),
                CallbackQueryHandler(edit_field_photo_prompt,      pattern=r"^edit:wldr_photo:"),
                CallbackQueryHandler(edit_field_bdate_prompt,      pattern=r"^edit:wldr_bdate:"),
                CallbackQueryHandler(welder_detail_callback,       pattern=r"^wldr:\d+$"),
            ],
            WLD_CRUD_EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field_name_save),
            ],
            WLD_CRUD_EDIT_CONTRACTOR: [
                CallbackQueryHandler(edit_field_contractor_save, pattern=r"^cntr:\d+$"),
            ],
            WLD_CRUD_EDIT_PHOTO: [
                MessageHandler(filters.PHOTO, edit_field_photo_save),
            ],
            WLD_CRUD_EDIT_BDATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field_bdate_save),
            ],
            # ── حذف جوشکار ─────────────────────────────────────────────
            WLD_CRUD_CONFIRM_DELETE: [
                CallbackQueryHandler(delete_welder_execute,   pattern=r"^wldr_del_yes:\d+$"),
                CallbackQueryHandler(welder_detail_callback,  pattern=r"^wldr:\d+$"),
            ],
            # ── جستجو ──────────────────────────────────────────────────
            WLD_CRUD_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, search_execute),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", _cancel_welder_conv),
            CommandHandler("start",  _cancel_welder_conv),
            CallbackQueryHandler(main_menu_callback_fallback, pattern=r"^menu:main$"),
        ],
        per_message=False,  # مطابق CONTRACTS.md
        name="welder_crud",
        persistent=False,
    )


async def _cancel_welder_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """لغو مکالمه جوشکار و بازگشت به منوی اصلی."""
    context.user_data.pop(_KEY_NEW_WELDER, None)
    context.user_data.pop(_KEY_EDIT_ID,    None)
    context.user_data.pop("wld_delete_id", None)

    role = context.user_data.get("role", "operator")
    if update.message:
        await update.message.reply_text(
            "❌ عملیات لغو شد.",
            reply_markup=main_menu_keyboard(role),
        )
    return ConversationHandler.END


async def main_menu_callback_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fallback برای بازگشت به منو از داخل مکالمه."""
    query = update.callback_query
    await query.answer()
    role = context.user_data.get("role", "operator")
    await query.edit_message_text(
        "🏠 منوی اصلی:",
        reply_markup=main_menu_keyboard(role),
    )
    return ConversationHandler.END


def get_welder_plain_handlers() -> list:
    """
    هندلرهای ساده (غیر-conversation) مربوط به جوشکاران.
    برای ثبت در main.py.
    """
    return [
        CallbackQueryHandler(show_welders_menu,     pattern=r"^menu:welders$"),
        CallbackQueryHandler(show_welders_list,      pattern=r"^cntr:\d+$"),
        CallbackQueryHandler(welders_page_callback,  pattern=r"^wldr_page:\d+$"),
        CallbackQueryHandler(welder_detail_callback, pattern=r"^wldr:\d+$"),
    ]
