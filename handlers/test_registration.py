"""
ماژول test_registration — بازطراحی کامل مطابق WelderBot_ASME_Spec_v2_4.md.

این نسخه جایگزین کامل جریان ثبت آزمون WQT قدیمی است. تغییرات اصلی نسبت به نسخه قبل:
  • Navigation Stack سراسری (بازگشت به مرحله قبل / انصراف / منوی اصلی با تاییدیه)
  • ترتیب مراحل جدید: پروژه → پیمانکار → (جوشکار جدید | آزمون مجدد)
  • فرم ASME کاملاً جدید: Process تک‌انتخابی (SMAW/GTAW/GTAW+SMAW)، Position/Diameter/
    Thickness/Material/Filler/Gas/Electrical بر اساس Rule Matrix های engine.qualification
  • Inspection Workflow (Visual → RT برای Groove | Visual → Fracture → Macro برای Fillet)
  • مدیریت Pending RT (منوی جدا، الگوی Deactivate+Reinsert)
  • بخش‌های بدون تغییر طبق تصمیم صریح شما: تاریخ انقضا، امضاکننده، تولید Excel

مرجع طراحی: WelderBot_ASME_Spec_v2_4.md
"""

from __future__ import annotations
from engine.report_builder import build_wpq_excel
import logging
import os
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    PhotoSize,
    Update,
)
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from db.models import (
    add_qualification,
    add_welder,
    get_expiring_qualifications,
    get_qualification_by_id,
    get_welder_by_id,
    get_welder_by_national_id,
    list_contractors,
    list_projects,
    list_welders_by_contractor,
    search_welders,
    set_qualification_inactive,
    get_user_by_telegram_id,
)
from engine.qualification import (
    GTAW_FILLERS,
    PROCESS_OPTIONS,
    QualificationEngine,
    QualificationValidationError,
    SMAW_ELECTRODES,
    get_materials,
    get_valid_positions,
)
from handlers.auth import get_role, require_auth
from handlers.keyboards import main_menu_keyboard
from utils.dates import (
    compute_expiry_date,
    gregorian_to_jalali,
    jalali_to_gregorian,
    validate_jalali_date_str,
)
from utils.validators import (
    validate_name,
    validate_national_id,
    validate_positive_float,
    validate_positive_int,
)

logger = logging.getLogger(__name__)

# ── instance مشترک engine (pure، بدون state داخلی) ────────────────────────────
_engine = QualificationEngine()

# ══════════════════════════════════════════════════════════════════════════════
# ثابت‌های state — نسخه ۲.۴ (جایگزین کامل CONTRACTS.md قدیم)
# ══════════════════════════════════════════════════════════════════════════════
(
    SELECT_PROJECT,                # 0  پروژه
    SELECT_CONTRACTOR,             # 1  پیمانکار
    SELECT_NEW_OR_RETEST,          # 2  ثبت جدید / آزمون مجدد
    SEARCH_WELDER,                 # 3  [آزمون مجدد] عبارت جستجو
    SELECT_WELDER_FROM_SEARCH,     # 4  [آزمون مجدد] انتخاب از نتایج
    INPUT_WELDER_NAME,             # 5  [جدید] نام و نام‌خانوادگی
    INPUT_WELDER_NATIONAL_ID,      # 6  [جدید] کد ملی
    INPUT_WELDER_PHONE,            # 7  [جدید] شماره تماس
    INPUT_WELDER_PHOTO,            # 8  [جدید] عکس
    ASK_ADDITIONAL_WELDER_INFO,    # 9  [جدید] افزودن اطلاعات تکمیلی؟
    INPUT_WELDER_ID_NO,            # 10 [جدید] Welder ID
    INPUT_COUPON_NO,               # 11 [جدید] Coupon No
    INPUT_WPS_NO,                  # 12 [جدید] WPS No
    INPUT_WQT_NO,                  # 13 [جدید] WQT No
    SELECT_PROCESS,                # 14 SMAW/GTAW/GTAW+SMAW
    SELECT_SPECIMEN_TYPE,          # 15 Plate/Pipe
    SELECT_JOINT_TYPE,             # 16 Groove/Fillet
    INPUT_PIPE_OD,                 # 17 [فقط Pipe]
    SELECT_TEST_POSITION,          # 18 Dynamic
    INPUT_BASE_METAL_THICKNESS,    # 19 [SMAW-تنها/GTAW-تنها + Groove]
    INPUT_PASS_COUNT,              # 20 [شرطی، ضخامت>=13]
    INPUT_GTAW_DEPOSIT_THK,        # 21 [GTAW+SMAW + Groove]
    INPUT_GTAW_PASS_COUNT,         # 22 [شرطی]
    INPUT_SMAW_DEPOSIT_THK,        # 23 [GTAW+SMAW + Groove]
    INPUT_SMAW_PASS_COUNT,         # 24 [شرطی]
    SELECT_MATERIAL,               # 25 از لیست یا Manual
    INPUT_MATERIAL_DESIGNATION,    # 26 [Manual]
    INPUT_MATERIAL_P_NO,           # 27 [Manual]
    SELECT_GTAW_FILLER,            # 28 [اگر GTAW فعال]
    INPUT_GTAW_FILLER_DESIGNATION, # 29 [Manual]
    INPUT_GTAW_FILLER_F_NO,        # 30 [Manual]
    INPUT_GTAW_FILLER_SFA,         # 31 [Manual]
    SELECT_SMAW_ELECTRODE,         # 32 [اگر SMAW فعال]
    INPUT_SMAW_ELECTRODE_DESIGNATION,  # 33 [Manual]
    INPUT_SMAW_ELECTRODE_F_NO,     # 34 [Manual]
    INPUT_SMAW_ELECTRODE_SFA,      # 35 [Manual]
    SELECT_SHIELDING_GAS,          # 36 [اگر GTAW فعال]
    INPUT_SHIELDING_GAS_MANUAL,    # 37 [Manual]
    SELECT_GTAW_CURRENT,           # 38 [اگر GTAW فعال]
    SELECT_GTAW_POLARITY,          # 39 [شرطی DC]
    SELECT_SMAW_CURRENT,           # 40 [اگر SMAW فعال]
    SELECT_SMAW_POLARITY,          # 41 [شرطی DC]
    INPUT_TEST_DATE,               # 42
    SELECT_VISUAL_GROOVE,          # 43 [Joint=Groove]
    SELECT_RT_RESULT,              # 44 [Joint=Groove، Visual=ACC]
    SELECT_VISUAL_FILLET,          # 45 [Joint=Fillet]
    SELECT_FRACTURE_RESULT,        # 46 [Joint=Fillet، Visual=ACC]
    SELECT_MACRO_RESULT,           # 47 [Joint=Fillet، Fracture=ACC]
    INPUT_EXPIRY_DATE,             # 48 [بدون تغییر نسبت به نسخه قبل]
    INPUT_SIGNER_NAME,             # 49 [بدون تغییر]
    INPUT_SIGNER_TITLE,            # 50 [بدون تغییر]
    SHOW_FINAL_SUMMARY,            # 51 خلاصه نهایی
    CONFIRM_AND_SAVE,              # 52 تایید نهایی
    ASK_GENERATE_EXCEL,            # 53 [بدون تغییر]
    PENDING_RT_FILTER,             # 54 [منوی جدا] فیلتر/نمایش
    PENDING_RT_SELECT,             # 55 [منوی جدا] انتخاب آیتم
    PENDING_RT_RESULT,             # 56 [منوی جدا] ثبت نتیجه ACC/REJ
    PENDING_RT_EXPIRY,             # 57 [منوی جدا، فقط اگر ACC]
    PENDING_RT_SIGNER_NAME,        # 58 [منوی جدا، فقط اگر ACC]
    PENDING_RT_SIGNER_TITLE,       # 59 [منوی جدا، فقط اگر ACC]
) = range(60)

# ── کلید namespace در context.user_data ──────────────────────────────────────
_NS = "wqt"


def _d(context: ContextTypes.DEFAULT_TYPE) -> dict:
    if _NS not in context.user_data:
        context.user_data[_NS] = {}
    return context.user_data[_NS]


def _clear(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(_NS, None)


def _push(context: ContextTypes.DEFAULT_TYPE, state: int) -> None:
    """State فعلی را پیش از رفتن به مرحله بعد، روی Stack تاریخچه می‌گذارد."""
    _d(context).setdefault("_stack", []).append(state)


# ══════════════════════════════════════════════════════════════════════════════
# Navigation — بخش اول اسپک: بازگشت / انصراف / منوی اصلی (سراسری، از هر مرحله)
# ══════════════════════════════════════════════════════════════════════════════

def _nav_row() -> list[tuple[str, str]]:
    return [("⬅️ قبلی", "nav:back"), ("❌ انصراف", "nav:cancel"), ("🏠 منو", "nav:home")]


def _kb(rows: list[list[tuple[str, str]]], nav: bool = True) -> InlineKeyboardMarkup:
    """سازنده keyboard از لیست (label, callback_data)؛ به‌طور پیش‌فرض ردیف Navigation اضافه می‌شود."""
    all_rows = list(rows)
    if nav:
        all_rows.append(_nav_row())
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=cd) for label, cd in row]
        for row in all_rows
    ])


async def _render(update_or_query, context: ContextTypes.DEFAULT_TYPE, text: str,
                   reply_markup: InlineKeyboardMarkup, parse_mode: str | None = "Markdown") -> None:
    """نمایش پیام از هر دو نوع ورودی (Update با message، یا CallbackQuery مستقیم)."""
    if hasattr(update_or_query, "edit_message_text"):
        await update_or_query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    elif hasattr(update_or_query, "callback_query") and update_or_query.callback_query:
        await update_or_query.callback_query.edit_message_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    elif hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    else:
        await update_or_query.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)


async def nav_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """دکمه ⬅️ قبلی — از fallbacks سراسری، در هر state قابل استفاده."""
    query = update.callback_query
    await query.answer()
    stack = _d(context).get("_stack", [])
    if not stack:
        await query.answer("این اولین مرحله است.", show_alert=True)
        current = _d(context).get("_current_state", SELECT_PROJECT)
        renderer = _STATE_RENDERERS.get(current)
        if renderer:
            return await renderer(query, context)
        return SELECT_PROJECT

    prev_state = stack.pop()
    renderer = _STATE_RENDERERS.get(prev_state)
    if renderer is None:
        logger.warning("renderer یافت نشد برای state=%s", prev_state)
        return await nav_back(update, context)
    _d(context)["_current_state"] = prev_state
    return await renderer(query, context)


async def nav_cancel_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    current = _d(context).get("_current_state", SELECT_PROJECT)
    await query.edit_message_text(
        "❌ آیا از انصراف مطمئن هستید؟ تمام اطلاعات این ثبت از بین می‌رود.",
        reply_markup=_kb([[("✅ بله، انصراف", "nav:cancel_yes")],
                           [("↩️ نه، ادامه بده", "nav:cancel_no")]], nav=False),
    )
    return current


async def nav_home_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    current = _d(context).get("_current_state", SELECT_PROJECT)
    await query.edit_message_text(
        "🏠 آیا می‌خواهید به منوی اصلی بازگردید؟ تمام اطلاعات این ثبت از بین می‌رود.",
        reply_markup=_kb([[("✅ بله، برو به منو", "nav:home_yes")],
                           [("↩️ نه، ادامه بده", "nav:home_no")]], nav=False),
    )
    return current


async def nav_cancel_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    role = context.user_data.get("role", "operator")
    _clear(context)
    await query.edit_message_text("❌ ثبت آزمون لغو شد.", reply_markup=main_menu_keyboard(role))
    return ConversationHandler.END


# nav:home_yes از همان منطق nav:cancel_yes استفاده می‌کند (خروجی یکسان، فقط پیام محرک متفاوت بود)
nav_home_yes = nav_cancel_yes


async def nav_cancel_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    current = _d(context).get("_current_state", SELECT_PROJECT)
    renderer = _STATE_RENDERERS.get(current)
    if renderer:
        return await renderer(query, context)
    return current


nav_home_no = nav_cancel_no


async def _err(update: Update, step: str) -> None:
    text = f"❌ خطایی در مرحله «{step}» رخ داد.\nلطفاً /cancel بزنید و دوباره تلاش کنید."
    if update.callback_query:
        try:
            await update.callback_query.answer(text[:200], show_alert=True)
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(text)


# ══════════════════════════════════════════════════════════════════════════════
# Keyboardهای اختصاصی هر مرحله
# ══════════════════════════════════════════════════════════════════════════════

def _projects_kb(projects: list[dict]) -> InlineKeyboardMarkup:
    rows = [[(f"📁 {p['name']}", f"proj:{p['id']}")] for p in projects]
    return _kb(rows)


def _contractors_kb(contractors: list[dict]) -> InlineKeyboardMarkup:
    rows = [[(f"🏢 {c['name']}", f"cntr:{c['id']}")] for c in contractors]
    return _kb(rows)


def _new_or_retest_kb() -> InlineKeyboardMarkup:
    return _kb([
        [("➕ ثبت جوشکار جدید", "newretest:new")],
        [("🔁 آزمون مجدد جوشکار", "newretest:retest")],
    ])


def _welder_search_results_kb(welders: list[dict]) -> InlineKeyboardMarkup:
    rows = [[(f"👷 {w['full_name']} ({w['national_id']})", f"wldrsel:{w['id']}")] for w in welders]
    return _kb(rows)


def _skip_kb(callback: str) -> InlineKeyboardMarkup:
    return _kb([[("⏭ رد کردن", callback)]])


def _yes_no_kb(yes_cb: str, no_cb: str, yes_label: str, no_label: str) -> InlineKeyboardMarkup:
    return _kb([[(yes_label, yes_cb)], [(no_label, no_cb)]])


def _process_kb() -> InlineKeyboardMarkup:
    return _kb([[(p, f"proc:{p}")] for p in PROCESS_OPTIONS])


def _specimen_kb() -> InlineKeyboardMarkup:
    return _kb([
        [("🟦 ورق (Plate)", "spec:PLATE")],
        [("🔵 لوله (Pipe)",  "spec:PIPE")],
    ])


def _joint_kb() -> InlineKeyboardMarkup:
    return _kb([
        [("🔷 Groove", "jtype:GROOVE")],
        [("🔶 Fillet", "jtype:FILLET")],
    ])


def _position_kb(specimen_type: str, joint_type: str) -> InlineKeyboardMarkup:
    positions = get_valid_positions(specimen_type, joint_type)
    return _kb([[(p, f"pos:{p}")] for p in positions])


def _material_kb(specimen_type: str) -> InlineKeyboardMarkup:
    materials = get_materials(specimen_type)
    rows = [[(f"{m['designation']} ({m['p_no']})", f"mat:{m['designation']}")] for m in materials]
    rows.append([("✍️ افزودن متریال دستی", "mat:MANUAL")])
    return _kb(rows)


def _gtaw_filler_kb() -> InlineKeyboardMarkup:
    rows = [[(f"{f['designation']} ({f['f_no']})", f"gfil:{f['designation']}")] for f in GTAW_FILLERS]
    rows.append([("✍️ افزودن فیلر دستی", "gfil:MANUAL")])
    return _kb(rows)


def _smaw_electrode_kb() -> InlineKeyboardMarkup:
    rows = [[(f"{e['designation']} ({e['f_no']})", f"sele:{e['designation']}")] for e in SMAW_ELECTRODES]
    rows.append([("✍️ افزودن الکترود دستی", "sele:MANUAL")])
    return _kb(rows)


def _shielding_gas_kb() -> InlineKeyboardMarkup:
    return _kb([
        [("Argon 99.9% (پیش‌فرض)", "gas:DEFAULT")],
        [("✍️ وارد کردن دستی", "gas:MANUAL")],
    ])


def _current_kb(prefix: str) -> InlineKeyboardMarkup:
    return _kb([[("AC", f"{prefix}:AC")], [("DC", f"{prefix}:DC")]])


def _polarity_kb(prefix: str) -> InlineKeyboardMarkup:
    return _kb([[("DCEP", f"{prefix}:DCEP")], [("DCEN", f"{prefix}:DCEN")]])


def _acc_rej_kb(prefix: str, extra: list[tuple[str, str]] | None = None) -> InlineKeyboardMarkup:
    rows = [[("✅ ACC (قبول)", f"{prefix}:ACC")], [("❌ REJ (رد)", f"{prefix}:REJ")]]
    if extra:
        rows.append(extra)
    return _kb(rows)


def _confirm_save_kb() -> InlineKeyboardMarkup:
    return _kb([[("✅ تأیید و ذخیره", "confirm:yes")], [("❌ لغو", "confirm:no")]])


def _excel_kb() -> InlineKeyboardMarkup:
    return _kb([
        [("📊 بله، Excel دانلود کن", "excel:yes")],
        [("⏭ خیر", "excel:no")],
    ], nav=False)


# ══════════════════════════════════════════════════════════════════════════════
# قالب‌بندی متن
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_list(lst) -> str:
    if isinstance(lst, str):
        return lst
    return "، ".join(lst) if lst else "—"


def _fmt_results(qr: dict) -> str:
    return (
        "📋 *دامنه صلاحیت محاسبه‌شده (ASME Sec. IX):*\n\n"
        f"⚙️ فرآیند:        `{qr['qr_process']}`\n"
        f"🔩 Backing:       `{qr['qr_backing']}`\n"
        f"🔷 P-Number:      `{_fmt_list(qr['qr_p_no'])}`\n"
        f"📏 ضخامت:         `{qr['qr_thickness']}`\n"
        f"🔵 قطر:           `{qr['qr_diameter']}`\n"
        f"📐 موقعیت Groove: `{_fmt_list(qr['qr_position_groove'])}`\n"
        f"📐 موقعیت Fillet: `{_fmt_list(qr['qr_position_fillet'])}`\n"
        f"🔧 F-Number:      `{_fmt_list(qr['qr_f_no'])}`\n"
        f"↗️ Progression:   `{qr.get('progression') or 'N/A'}`\n"
    )


def _fmt_final_summary(d: dict) -> str:
    test_date_j = d.get("test_date_j", "—")
    status_map = {"QUALIFIED": "✅ Qualified", "REJECTED": "❌ Rejected", "PENDING_RT": "🕒 Pending RT"}
    status = status_map.get(d.get("final_status"), d.get("final_status", "—"))

    lines = [
        "📝 *خلاصه ثبت آزمون WQT*\n",
        f"📁 پروژه: {d.get('project_name', '—')}",
        f"🏢 پیمانکار: {d.get('contractor_name', '—')}",
        f"👷 جوشکار: {d.get('welder_name', '—')} (`{d.get('welder_national_id', '—')}`)\n",
        f"⚙️ فرآیند: {d.get('process', '—')}",
        f"🔵 نمونه: {d.get('specimen_type', '—')} | اتصال: {d.get('joint_type', '—')}",
        f"📌 موقعیت: {d.get('test_position', '—')}",
        f"📅 تاریخ آزمون: {test_date_j}",
        f"\n🔎 نتیجه بازرسی: {status}",
        "",
        _fmt_results(d.get("qr_result", {})) if d.get("qr_result") else "",
    ]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# اعتبارسنجی محلی (فقط داخل همین فایل — utils/validators.py قابل تغییر نیست)
# ══════════════════════════════════════════════════════════════════════════════

def _validate_phone_ir(text: str) -> bool:
    """شماره موبایل ایران: 09xxxxxxxxx (۱۱ رقم)."""
    t = text.strip()
    return t.isdigit() and len(t) == 11 and t.startswith("09")


# ══════════════════════════════════════════════════════════════════════════════
# مرحله ۰: انتخاب پروژه — SELECT_PROJECT
# ══════════════════════════════════════════════════════════════════════════════

@require_auth
async def reg_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _clear(context)
        projects = list_projects(active_only=True)
        if not projects:
            text = "⚠️ هیچ پروژه‌ای ثبت نشده است."
            role = context.user_data.get("role", "operator")
            if update.callback_query:
                await update.callback_query.answer()
                await update.callback_query.edit_message_text(text, reply_markup=main_menu_keyboard(role))
            else:
                await update.message.reply_text(text, reply_markup=main_menu_keyboard(role))
            return ConversationHandler.END

        _d(context)["projects"] = {p["id"]: p for p in projects}
        _d(context)["_current_state"] = SELECT_PROJECT
        text = "📋 *ثبت آزمون WQT*\n\n📁 پروژه را انتخاب کنید:"
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=_projects_kb(projects))
        else:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=_projects_kb(projects))
        return SELECT_PROJECT
    except Exception:
        logger.exception("خطا در reg_start")
        await _err(update, "شروع ثبت آزمون")
        return ConversationHandler.END


async def _render_select_project(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    projects = list(_d(context).get("projects", {}).values())
    await q.edit_message_text("📋 *ثبت آزمون WQT*\n\n📁 پروژه را انتخاب کنید:",
                               parse_mode="Markdown", reply_markup=_projects_kb(projects))
    return SELECT_PROJECT


async def step_select_project(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        project_id = int(query.data.split(":")[1])
        project = _d(context).get("projects", {}).get(project_id)
        if not project:
            await query.edit_message_text("⚠️ پروژه یافت نشد.")
            return ConversationHandler.END

        _d(context)["project_id"] = project_id
        _d(context)["project_name"] = project["name"]
        _push(context, SELECT_PROJECT)
        return await _render_select_contractor(query, context)
    except Exception:
        logger.exception("خطا در step_select_project")
        await _err(update, "انتخاب پروژه")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# مرحله ۱: انتخاب پیمانکار — SELECT_CONTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_contractor(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    contractors = list_contractors(active_only=True)
    _d(context)["contractors"] = {c["id"]: c for c in contractors}
    _d(context)["_current_state"] = SELECT_CONTRACTOR
    await q.edit_message_text(
        f"✅ پروژه: *{_d(context)['project_name']}*\n\n🏢 پیمانکار را انتخاب کنید:",
        parse_mode="Markdown", reply_markup=_contractors_kb(contractors),
    )
    return SELECT_CONTRACTOR


async def step_select_contractor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        contractor_id = int(query.data.split(":")[1])
        contractor = _d(context).get("contractors", {}).get(contractor_id)
        if not contractor:
            await query.edit_message_text("⚠️ پیمانکار یافت نشد.")
            return ConversationHandler.END

        _d(context)["contractor_id"] = contractor_id
        _d(context)["contractor_name"] = contractor["name"]
        _push(context, SELECT_CONTRACTOR)
        return await _render_new_or_retest(query, context)
    except Exception:
        logger.exception("خطا در step_select_contractor")
        await _err(update, "انتخاب پیمانکار")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# مرحله ۲: ثبت جدید یا آزمون مجدد — SELECT_NEW_OR_RETEST
# ══════════════════════════════════════════════════════════════════════════════

async def _render_new_or_retest(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_NEW_OR_RETEST
    await q.edit_message_text(
        f"🏢 پیمانکار: *{_d(context)['contractor_name']}*\n\nنوع عملیات را انتخاب کنید:",
        parse_mode="Markdown", reply_markup=_new_or_retest_kb(),
    )
    return SELECT_NEW_OR_RETEST


async def step_new_or_retest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        choice = query.data.split(":")[1]
        _push(context, SELECT_NEW_OR_RETEST)

        if choice == "new":
            return await _render_input_welder_name(query, context)
        else:
            return await _render_search_welder(query, context)
    except Exception:
        logger.exception("خطا در step_new_or_retest")
        await _err(update, "انتخاب نوع عملیات")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# مسیر آزمون مجدد: جستجوی جوشکار — SEARCH_WELDER / SELECT_WELDER_FROM_SEARCH
# ══════════════════════════════════════════════════════════════════════════════

async def _render_search_welder(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SEARCH_WELDER
    await q.edit_message_text(
        "🔎 نام، نام‌خانوادگی یا کد ملی جوشکار را برای جستجو وارد کنید:",
        reply_markup=_kb([], nav=True),
    )
    return SEARCH_WELDER


async def step_search_welder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query_text = update.message.text.strip()
        if len(query_text) < 2:
            await update.message.reply_text("⚠️ حداقل ۲ کاراکتر وارد کنید:")
            return SEARCH_WELDER

        results = search_welders(query_text)
        if not results:
            await update.message.reply_text(
                "⚠️ جوشکاری یافت نشد. دوباره جستجو کنید یا از منوی navigation بازگردید:"
            )
            return SEARCH_WELDER

        _d(context)["search_results"] = {w["id"]: w for w in results}
        _push(context, SEARCH_WELDER)
        _d(context)["_current_state"] = SELECT_WELDER_FROM_SEARCH
        await update.message.reply_text(
            f"🔎 {len(results)} نتیجه یافت شد:",
            reply_markup=_welder_search_results_kb(results),
        )
        return SELECT_WELDER_FROM_SEARCH
    except Exception:
        logger.exception("خطا در step_search_welder")
        await _err(update, "جستجوی جوشکار")
        return ConversationHandler.END


async def _render_select_welder_from_search(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    results = list(_d(context).get("search_results", {}).values())
    _d(context)["_current_state"] = SELECT_WELDER_FROM_SEARCH
    await q.edit_message_text(f"🔎 {len(results)} نتیجه یافت شد:",
                               reply_markup=_welder_search_results_kb(results))
    return SELECT_WELDER_FROM_SEARCH


async def step_select_welder_from_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        welder_id = int(query.data.split(":")[1])
        welder = _d(context).get("search_results", {}).get(welder_id)
        if not welder:
            await query.edit_message_text("⚠️ جوشکار یافت نشد.")
            return ConversationHandler.END

        _d(context)["welder_id"] = welder_id
        _d(context)["welder_name"] = welder["full_name"]
        _d(context)["welder_national_id"] = welder["national_id"]
        _push(context, SELECT_WELDER_FROM_SEARCH)
        return await _render_select_process(query, context)
    except Exception:
        logger.exception("خطا در step_select_welder_from_search")
        await _err(update, "انتخاب جوشکار")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# مسیر جوشکار جدید: نام → کد ملی → تلفن → عکس → اطلاعات تکمیلی
# ══════════════════════════════════════════════════════════════════════════════

async def _render_input_welder_name(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_WELDER_NAME
    prev = _d(context).get("new_welder_name")
    hint = f"\n(مقدار قبلی: {prev})" if prev else ""
    await q.edit_message_text(f"➕ *ثبت جوشکار جدید*\n\n👷 نام و نام‌خانوادگی را وارد کنید:{hint}",
                               parse_mode="Markdown", reply_markup=_kb([]))
    return INPUT_WELDER_NAME


async def step_welder_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        text = update.message.text.strip()
        if not validate_name(text):
            await update.message.reply_text("⚠️ نام معتبر نیست. دوباره وارد کنید:")
            return INPUT_WELDER_NAME
        _d(context)["new_welder_name"] = text
        _push(context, INPUT_WELDER_NAME)
        await update.message.reply_text("🪪 کد ملی ۱۰ رقمی را وارد کنید:")
        _d(context)["_current_state"] = INPUT_WELDER_NATIONAL_ID
        return INPUT_WELDER_NATIONAL_ID
    except Exception:
        logger.exception("خطا در step_welder_name")
        await _err(update, "نام جوشکار")
        return ConversationHandler.END


async def _render_input_national_id(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_WELDER_NATIONAL_ID
    await q.edit_message_text("🪪 کد ملی ۱۰ رقمی را وارد کنید:", reply_markup=_kb([]))
    return INPUT_WELDER_NATIONAL_ID


async def step_welder_national_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        text = update.message.text.strip()
        if not validate_national_id(text):
            await update.message.reply_text("⚠️ کد ملی معتبر نیست (۱۰ رقم). دوباره وارد کنید:")
            return INPUT_WELDER_NATIONAL_ID

        existing = get_welder_by_national_id(text)
        if existing:
            await update.message.reply_text(
                f"⚠️ جوشکاری با این کد ملی از قبل ثبت شده: *{existing['full_name']}*\n"
                "اگر قصد آزمون مجدد دارید، از مسیر «آزمون مجدد» استفاده کنید.\n"
                "کد ملی دیگری وارد کنید:", parse_mode="Markdown",
            )
            return INPUT_WELDER_NATIONAL_ID

        _d(context)["new_welder_national_id"] = text
        _push(context, INPUT_WELDER_NATIONAL_ID)
        await update.message.reply_text("📱 شماره تماس را وارد کنید (مثال: 09121234567):")
        _d(context)["_current_state"] = INPUT_WELDER_PHONE
        return INPUT_WELDER_PHONE
    except Exception:
        logger.exception("خطا در step_welder_national_id")
        await _err(update, "کد ملی جوشکار")
        return ConversationHandler.END


async def _render_input_phone(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_WELDER_PHONE
    await q.edit_message_text("📱 شماره تماس را وارد کنید (مثال: 09121234567):", reply_markup=_kb([]))
    return INPUT_WELDER_PHONE


async def step_welder_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        text = update.message.text.strip()
        if not _validate_phone_ir(text):
            await update.message.reply_text("⚠️ شماره معتبر نیست (باید 09 و ۱۱ رقم باشد). دوباره وارد کنید:")
            return INPUT_WELDER_PHONE
        _d(context)["new_welder_phone"] = text
        _push(context, INPUT_WELDER_PHONE)
        _d(context)["_current_state"] = INPUT_WELDER_PHOTO
        await update.message.reply_text("📷 عکس جوشکار را ارسال کنید (یا رد کنید):",
                                         reply_markup=_skip_kb("skip:photo"))
        return INPUT_WELDER_PHOTO
    except Exception:
        logger.exception("خطا در step_welder_phone")
        await _err(update, "شماره تماس جوشکار")
        return ConversationHandler.END


async def _render_input_photo(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_WELDER_PHOTO
    await q.edit_message_text("📷 عکس جوشکار را ارسال کنید (یا رد کنید):",
                               reply_markup=_skip_kb("skip:photo"))
    return INPUT_WELDER_PHOTO


async def step_welder_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        if update.message and update.message.photo:
            photo: PhotoSize = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            national = _d(context).get("new_welder_national_id", "unknown")
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"{national}_{timestamp}.jpg"
            full_path = os.path.join(config.MEDIA_PATH, filename)
            await file.download_to_drive(full_path)
            _d(context)["new_welder_photo"] = os.path.join("media", "photos", filename)
        else:
            await update.message.reply_text("⚠️ لطفاً تصویر ارسال کنید یا «رد کردن» را بزنید.",
                                             reply_markup=_skip_kb("skip:photo"))
            return INPUT_WELDER_PHOTO

        _push(context, INPUT_WELDER_PHOTO)
        return await _render_ask_additional_info(update.message, context)
    except Exception:
        logger.exception("خطا در step_welder_photo")
        await _err(update, "عکس جوشکار")
        return ConversationHandler.END


async def step_skip_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _d(context)["new_welder_photo"] = None
    _push(context, INPUT_WELDER_PHOTO)
    return await _render_ask_additional_info(query, context)


# ══════════════════════════════════════════════════════════════════════════════
# اطلاعات تکمیلی اختیاری: Welder ID / Coupon No / WPS No / WQT No
# نکته طراحی: چون add_welder() امضای ثابت دارد و جای این ۴ فیلد را ندارد،
# این مقادیر داخل extra_data رکورد qualification (نه پروفایل جوشکار) ذخیره می‌شوند.
# ══════════════════════════════════════════════════════════════════════════════

async def _render_ask_additional_info(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = ASK_ADDITIONAL_WELDER_INFO
    text = "➕ آیا می‌خواهید اطلاعات تکمیلی (Welder ID، Coupon No، WPS No، WQT No) وارد کنید؟"
    kb = _kb([[("➕ بله", "addinfo:yes")], [("⏭ خیر", "addinfo:no")]])
    await _render(msg_or_query, context, text, kb)
    return ASK_ADDITIONAL_WELDER_INFO


async def step_ask_additional_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        choice = query.data.split(":")[1]
        _push(context, ASK_ADDITIONAL_WELDER_INFO)
        if choice == "no":
            return await _finish_new_welder(query, context)
        _d(context)["_current_state"] = INPUT_WELDER_ID_NO
        await query.edit_message_text("🆔 Welder ID را وارد کنید (یا رد کنید):",
                                       reply_markup=_skip_kb("skip:welder_id_no"))
        return INPUT_WELDER_ID_NO
    except Exception:
        logger.exception("خطا در step_ask_additional_info")
        await _err(update, "اطلاعات تکمیلی")
        return ConversationHandler.END


async def _chain_text_step(update, context, store_key: str, next_state: int, next_prompt: str,
                            next_skip_cb: str | None, push_state: int) -> int:
    """الگوی مشترک برای زنجیره Welder ID → Coupon No → WPS No → WQT No."""
    text = update.message.text.strip()
    _d(context)[store_key] = text
    _push(context, push_state)
    _d(context)["_current_state"] = next_state
    kb = _skip_kb(next_skip_cb) if next_skip_cb else _kb([])
    await update.message.reply_text(next_prompt, reply_markup=kb)
    return next_state


async def step_input_welder_id_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        return await _chain_text_step(update, context, "welder_id_no", INPUT_COUPON_NO,
                                       "🧪 Coupon No را وارد کنید (یا رد کنید):",
                                       "skip:coupon_no", INPUT_WELDER_ID_NO)
    except Exception:
        logger.exception("خطا در step_input_welder_id_no")
        await _err(update, "Welder ID")
        return ConversationHandler.END


async def step_skip_welder_id_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _d(context)["welder_id_no"] = None
    _push(context, INPUT_WELDER_ID_NO)
    _d(context)["_current_state"] = INPUT_COUPON_NO
    await query.edit_message_text("🧪 Coupon No را وارد کنید (یا رد کنید):", reply_markup=_skip_kb("skip:coupon_no"))
    return INPUT_COUPON_NO


async def step_input_coupon_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        return await _chain_text_step(update, context, "coupon_no", INPUT_WPS_NO,
                                       "📄 WPS No را وارد کنید (یا رد کنید):",
                                       "skip:wps_no", INPUT_COUPON_NO)
    except Exception:
        logger.exception("خطا در step_input_coupon_no")
        await _err(update, "Coupon No")
        return ConversationHandler.END


async def step_skip_coupon_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _d(context)["coupon_no"] = None
    _push(context, INPUT_COUPON_NO)
    _d(context)["_current_state"] = INPUT_WPS_NO
    await query.edit_message_text("📄 WPS No را وارد کنید (یا رد کنید):", reply_markup=_skip_kb("skip:wps_no"))
    return INPUT_WPS_NO


async def step_input_wps_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        return await _chain_text_step(update, context, "wps_no", INPUT_WQT_NO,
                                       "📃 WQT No را وارد کنید (یا رد کنید):",
                                       "skip:wqt_no", INPUT_WPS_NO)
    except Exception:
        logger.exception("خطا در step_input_wps_no")
        await _err(update, "WPS No")
        return ConversationHandler.END


async def step_skip_wps_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _d(context)["wps_no"] = None
    _push(context, INPUT_WPS_NO)
    _d(context)["_current_state"] = INPUT_WQT_NO
    await query.edit_message_text("📃 WQT No را وارد کنید (یا رد کنید):", reply_markup=_skip_kb("skip:wqt_no"))
    return INPUT_WQT_NO


async def step_input_wqt_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _d(context)["wqt_no"] = update.message.text.strip()
        _push(context, INPUT_WQT_NO)
        return await _finish_new_welder(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_wqt_no")
        await _err(update, "WQT No")
        return ConversationHandler.END


async def step_skip_wqt_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _d(context)["wqt_no"] = None
    _push(context, INPUT_WQT_NO)
    return await _finish_new_welder(query, context)


async def _finish_new_welder(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """ثبت نهایی جوشکار جدید در DB با contractor_id گرفته‌شده از مرحله ۱ (بدون سوال تکراری)."""
    d = _d(context)
    new_id = add_welder(
        national_id=d["new_welder_national_id"],
        full_name=d["new_welder_name"],
        contractor_id=d["contractor_id"],
        photo_path=d.get("new_welder_photo"),
        birth_date=None,
    )
    d["welder_id"] = new_id
    d["welder_name"] = d["new_welder_name"]
    d["welder_national_id"] = d["new_welder_national_id"]
    logger.info("جوشکار جدید ثبت شد: id=%d", new_id)
    return await _render_select_process(msg_or_query, context)


# ══════════════════════════════════════════════════════════════════════════════
# فرم ASME — مرحله Process / Specimen / Joint / Pipe OD / Position
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_process(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_PROCESS
    await _render(msg_or_query, context, "⚙️ *فرم ASME*\n\nفرآیند جوشکاری را انتخاب کنید:",
                  _process_kb())
    return SELECT_PROCESS


async def step_select_process(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        process = query.data.split(":")[1]
        if process not in PROCESS_OPTIONS:
            await query.edit_message_text("⚠️ گزینه نامعتبر.")
            return ConversationHandler.END
        _d(context)["process"] = process
        _push(context, SELECT_PROCESS)
        _d(context)["_current_state"] = SELECT_SPECIMEN_TYPE
        await query.edit_message_text(f"✅ فرآیند: *{process}*\n\n🔵 نوع نمونه را انتخاب کنید:",
                                       parse_mode="Markdown", reply_markup=_specimen_kb())
        return SELECT_SPECIMEN_TYPE
    except Exception:
        logger.exception("خطا در step_select_process")
        await _err(update, "انتخاب فرآیند")
        return ConversationHandler.END


async def _render_select_specimen(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_SPECIMEN_TYPE
    await q.edit_message_text("🔵 نوع نمونه را انتخاب کنید:", reply_markup=_specimen_kb())
    return SELECT_SPECIMEN_TYPE


async def step_select_specimen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        specimen = query.data.split(":")[1]
        _d(context)["specimen_type"] = specimen
        _push(context, SELECT_SPECIMEN_TYPE)
        _d(context)["_current_state"] = SELECT_JOINT_TYPE
        await query.edit_message_text(f"✅ نمونه: *{specimen}*\n\n🔷 نوع اتصال را انتخاب کنید:",
                                       parse_mode="Markdown", reply_markup=_joint_kb())
        return SELECT_JOINT_TYPE
    except Exception:
        logger.exception("خطا در step_select_specimen")
        await _err(update, "نوع نمونه")
        return ConversationHandler.END


async def _render_select_joint(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_JOINT_TYPE
    await q.edit_message_text("🔷 نوع اتصال را انتخاب کنید:", reply_markup=_joint_kb())
    return SELECT_JOINT_TYPE


async def step_select_joint(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        joint = query.data.split(":")[1]
        _d(context)["joint_type"] = joint
        _push(context, SELECT_JOINT_TYPE)

        if _d(context)["specimen_type"] == "PIPE":
            _d(context)["_current_state"] = INPUT_PIPE_OD
            await query.edit_message_text(f"✅ اتصال: *{joint}*\n\n🔵 قطر خارجی لوله (OD) به میلی‌متر:",
                                           parse_mode="Markdown", reply_markup=_kb([]))
            return INPUT_PIPE_OD

        return await _render_select_position(query, context)
    except Exception:
        logger.exception("خطا در step_select_joint")
        await _err(update, "نوع اتصال")
        return ConversationHandler.END


async def _render_input_pipe_od(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_PIPE_OD
    await q.edit_message_text("🔵 قطر خارجی لوله (OD) به میلی‌متر:", reply_markup=_kb([]))
    return INPUT_PIPE_OD


async def step_input_pipe_od(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ok, val = validate_positive_float(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ عدد معتبر وارد کنید:")
            return INPUT_PIPE_OD
        if val >= 609.6:
            await update.message.reply_text(
                "⚠️ قطرهای ≥ 24 اینچ (609.6mm) در این نسخه پشتیبانی نمی‌شوند.\nعدد دیگری وارد کنید:"
            )
            return INPUT_PIPE_OD
        _d(context)["pipe_od_mm"] = val
        _push(context, INPUT_PIPE_OD)
        return await _render_select_position(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_pipe_od")
        await _err(update, "قطر لوله")
        return ConversationHandler.END


async def _render_select_position(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = _d(context)
    _d(context)["_current_state"] = SELECT_TEST_POSITION
    kb = _position_kb(d["specimen_type"], d["joint_type"])
    await _render(msg_or_query, context, "📌 موقعیت آزمون را انتخاب کنید:", kb)
    return SELECT_TEST_POSITION


async def step_select_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        position = query.data.split(":", 1)[1]
        _d(context)["test_position"] = position
        _push(context, SELECT_TEST_POSITION)

        d = _d(context)
        if d["joint_type"] == "FILLET":
            # طبق اسپک: بخش ضخامت هنوز برای Fillet طراحی نشده — مستقیم به متریال
            return await _render_select_material(query, context)

        if d["process"] == "GTAW+SMAW":
            _d(context)["_current_state"] = INPUT_GTAW_DEPOSIT_THK
            await query.edit_message_text("📏 ضخامت رسوب GTAW به میلی‌متر:", reply_markup=_kb([]))
            return INPUT_GTAW_DEPOSIT_THK
        else:
            _d(context)["_current_state"] = INPUT_BASE_METAL_THICKNESS
            await query.edit_message_text("📏 ضخامت فلز پایه به میلی‌متر:", reply_markup=_kb([]))
            return INPUT_BASE_METAL_THICKNESS
    except Exception:
        logger.exception("خطا در step_select_position")
        await _err(update, "موقعیت آزمون")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# QW-452.1(b) — ضخامت: حالت SMAW-تنها / GTAW-تنها (فیلد مشترک base_metal_thickness_mm)
# ══════════════════════════════════════════════════════════════════════════════

async def _render_input_base_thickness(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_BASE_METAL_THICKNESS
    await q.edit_message_text("📏 ضخامت فلز پایه به میلی‌متر:", reply_markup=_kb([]))
    return INPUT_BASE_METAL_THICKNESS


async def step_input_base_thickness(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ok, val = validate_positive_float(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ عدد معتبر وارد کنید:")
            return INPUT_BASE_METAL_THICKNESS
        _d(context)["base_metal_thickness_mm"] = val
        _push(context, INPUT_BASE_METAL_THICKNESS)

        if val < 13.0:
            return await _render_select_material(update.message, context)

        _d(context)["_current_state"] = INPUT_PASS_COUNT
        await update.message.reply_text(
            f"📏 ضخامت {val:.1f}mm ≥ 13mm است.\n🔢 تعداد پاس جوش را وارد کنید:"
        )
        return INPUT_PASS_COUNT
    except Exception:
        logger.exception("خطا در step_input_base_thickness")
        await _err(update, "ضخامت فلز پایه")
        return ConversationHandler.END


async def _render_input_pass_count(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_PASS_COUNT
    await q.edit_message_text("🔢 تعداد پاس جوش را وارد کنید:", reply_markup=_kb([]))
    return INPUT_PASS_COUNT


async def step_input_pass_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ok, val = validate_positive_int(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ عدد صحیح معتبر وارد کنید:")
            return INPUT_PASS_COUNT
        _d(context)["pass_count"] = val
        _push(context, INPUT_PASS_COUNT)
        return await _render_select_material(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_pass_count")
        await _err(update, "تعداد پاس")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# QW-452.1(b) — ضخامت: حالت GTAW+SMAW (دو محاسبه مستقل، بدون سوال ضخامت فلز پایه)
# ══════════════════════════════════════════════════════════════════════════════

async def _render_input_gtaw_thk(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_GTAW_DEPOSIT_THK
    await q.edit_message_text("📏 ضخامت رسوب GTAW به میلی‌متر:", reply_markup=_kb([]))
    return INPUT_GTAW_DEPOSIT_THK


async def step_input_gtaw_thk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ok, val = validate_positive_float(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ عدد معتبر وارد کنید:")
            return INPUT_GTAW_DEPOSIT_THK
        _d(context)["gtaw_deposit_thk_mm"] = val
        _push(context, INPUT_GTAW_DEPOSIT_THK)

        if val < 13.0:
            _d(context)["_current_state"] = INPUT_SMAW_DEPOSIT_THK
            await update.message.reply_text("📏 ضخامت رسوب SMAW به میلی‌متر:")
            return INPUT_SMAW_DEPOSIT_THK

        _d(context)["_current_state"] = INPUT_GTAW_PASS_COUNT
        await update.message.reply_text(f"📏 ضخامت GTAW {val:.1f}mm ≥ 13mm.\n🔢 تعداد پاس GTAW:")
        return INPUT_GTAW_PASS_COUNT
    except Exception:
        logger.exception("خطا در step_input_gtaw_thk")
        await _err(update, "ضخامت رسوب GTAW")
        return ConversationHandler.END


async def _render_input_gtaw_pass(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_GTAW_PASS_COUNT
    await q.edit_message_text("🔢 تعداد پاس GTAW:", reply_markup=_kb([]))
    return INPUT_GTAW_PASS_COUNT


async def step_input_gtaw_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ok, val = validate_positive_int(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ عدد صحیح معتبر وارد کنید:")
            return INPUT_GTAW_PASS_COUNT
        _d(context)["gtaw_pass_count"] = val
        _push(context, INPUT_GTAW_PASS_COUNT)
        _d(context)["_current_state"] = INPUT_SMAW_DEPOSIT_THK
        await update.message.reply_text("📏 ضخامت رسوب SMAW به میلی‌متر:")
        return INPUT_SMAW_DEPOSIT_THK
    except Exception:
        logger.exception("خطا در step_input_gtaw_pass")
        await _err(update, "تعداد پاس GTAW")
        return ConversationHandler.END


async def _render_input_smaw_thk(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_SMAW_DEPOSIT_THK
    await q.edit_message_text("📏 ضخامت رسوب SMAW به میلی‌متر:", reply_markup=_kb([]))
    return INPUT_SMAW_DEPOSIT_THK


async def step_input_smaw_thk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ok, val = validate_positive_float(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ عدد معتبر وارد کنید:")
            return INPUT_SMAW_DEPOSIT_THK
        _d(context)["smaw_deposit_thk_mm"] = val
        _push(context, INPUT_SMAW_DEPOSIT_THK)

        if val < 13.0:
            return await _render_select_material(update.message, context)

        _d(context)["_current_state"] = INPUT_SMAW_PASS_COUNT
        await update.message.reply_text(f"📏 ضخامت SMAW {val:.1f}mm ≥ 13mm.\n🔢 تعداد پاس SMAW:")
        return INPUT_SMAW_PASS_COUNT
    except Exception:
        logger.exception("خطا در step_input_smaw_thk")
        await _err(update, "ضخامت رسوب SMAW")
        return ConversationHandler.END


async def _render_input_smaw_pass(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_SMAW_PASS_COUNT
    await q.edit_message_text("🔢 تعداد پاس SMAW:", reply_markup=_kb([]))
    return INPUT_SMAW_PASS_COUNT


async def step_input_smaw_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        ok, val = validate_positive_int(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ عدد صحیح معتبر وارد کنید:")
            return INPUT_SMAW_PASS_COUNT
        _d(context)["smaw_pass_count"] = val
        _push(context, INPUT_SMAW_PASS_COUNT)
        return await _render_select_material(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_smaw_pass")
        await _err(update, "تعداد پاس SMAW")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# QW-423.1 — انتخاب متریال (از لیست یا دستی)
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_material(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = _d(context)
    _d(context)["_current_state"] = SELECT_MATERIAL
    kb = _material_kb(d["specimen_type"])
    await _render(msg_or_query, context, "🧱 متریال فلز پایه را انتخاب کنید:", kb)
    return SELECT_MATERIAL


async def step_select_material(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        choice = query.data.split(":", 1)[1]
        _push(context, SELECT_MATERIAL)

        if choice == "MANUAL":
            _d(context)["_current_state"] = INPUT_MATERIAL_DESIGNATION
            await query.edit_message_text("✍️ نام/کد متریال را وارد کنید:", reply_markup=_kb([]))
            return INPUT_MATERIAL_DESIGNATION

        materials = get_materials(_d(context)["specimen_type"])
        material = next((m for m in materials if m["designation"] == choice), None)
        if not material:
            await query.edit_message_text("⚠️ متریال یافت نشد.")
            return ConversationHandler.END

        _d(context)["base_metal_material"] = material["designation"]
        _d(context)["base_metal_p_no"] = material["p_no"]
        _d(context)["base_metal_is_manual"] = False
        return await _after_material(query, context)
    except Exception:
        logger.exception("خطا در step_select_material")
        await _err(update, "انتخاب متریال")
        return ConversationHandler.END


async def _render_input_material_designation(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_MATERIAL_DESIGNATION
    await q.edit_message_text("✍️ نام/کد متریال را وارد کنید:", reply_markup=_kb([]))
    return INPUT_MATERIAL_DESIGNATION


async def step_input_material_designation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _d(context)["base_metal_material"] = update.message.text.strip()
        _push(context, INPUT_MATERIAL_DESIGNATION)
        _d(context)["_current_state"] = INPUT_MATERIAL_P_NO
        await update.message.reply_text(
            "🔷 P-Number متریال را وارد کنید (مثال: P1 یا P-No. 6):"
        )
        return INPUT_MATERIAL_P_NO
    except Exception:
        logger.exception("خطا در step_input_material_designation")
        await _err(update, "نام متریال")
        return ConversationHandler.END


async def _render_input_material_p_no(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_MATERIAL_P_NO
    await q.edit_message_text("🔷 P-Number متریال را وارد کنید (مثال: P1 یا P-No. 6):", reply_markup=_kb([]))
    return INPUT_MATERIAL_P_NO


async def step_input_material_p_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        raw = update.message.text.strip().upper().replace("-NO.", "").replace(" ", "").replace(".", "")
        # نرمال‌سازی ساده: "P-No. 1" یا "P1" یا "p 1" همه به "P1" تبدیل می‌شوند
        normalized = "P" + raw.lstrip("P") if raw.startswith("P") else "P" + raw
        _d(context)["base_metal_p_no"] = normalized
        _d(context)["base_metal_is_manual"] = True
        _push(context, INPUT_MATERIAL_P_NO)
        return await _after_material(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_material_p_no")
        await _err(update, "P-Number متریال")
        return ConversationHandler.END


async def _after_material(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پس از متریال: اگر GTAW فعال → انتخاب فیلر GTAW؛ وگرنه مستقیم الکترود SMAW."""
    process = _d(context)["process"]
    if "GTAW" in process:
        return await _render_select_gtaw_filler(msg_or_query, context)
    return await _render_select_smaw_electrode(msg_or_query, context)


# ══════════════════════════════════════════════════════════════════════════════
# QW-433 — انتخاب فیلر GTAW
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_gtaw_filler(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_GTAW_FILLER
    await _render(msg_or_query, context, "🔧 فیلر GTAW را انتخاب کنید:", _gtaw_filler_kb())
    return SELECT_GTAW_FILLER


async def step_select_gtaw_filler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        choice = query.data.split(":", 1)[1]
        _push(context, SELECT_GTAW_FILLER)

        if choice == "MANUAL":
            _d(context)["_current_state"] = INPUT_GTAW_FILLER_DESIGNATION
            await query.edit_message_text("✍️ نام/کد فیلر GTAW را وارد کنید:", reply_markup=_kb([]))
            return INPUT_GTAW_FILLER_DESIGNATION

        filler = next((f for f in GTAW_FILLERS if f["designation"] == choice), None)
        if not filler:
            await query.edit_message_text("⚠️ فیلر یافت نشد.")
            return ConversationHandler.END
        _d(context)["filler_gtaw"] = dict(filler)
        return await _after_gtaw_filler(query, context)
    except Exception:
        logger.exception("خطا در step_select_gtaw_filler")
        await _err(update, "انتخاب فیلر GTAW")
        return ConversationHandler.END


async def _render_input_gtaw_filler_designation(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_GTAW_FILLER_DESIGNATION
    await q.edit_message_text("✍️ نام/کد فیلر GTAW را وارد کنید:", reply_markup=_kb([]))
    return INPUT_GTAW_FILLER_DESIGNATION


async def step_input_gtaw_filler_designation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _d(context).setdefault("filler_gtaw", {})["designation"] = update.message.text.strip()
        _push(context, INPUT_GTAW_FILLER_DESIGNATION)
        _d(context)["_current_state"] = INPUT_GTAW_FILLER_F_NO
        await update.message.reply_text("🔧 F-Number فیلر GTAW را وارد کنید (مثال: F6):")
        return INPUT_GTAW_FILLER_F_NO
    except Exception:
        logger.exception("خطا در step_input_gtaw_filler_designation")
        await _err(update, "نام فیلر GTAW")
        return ConversationHandler.END


async def _render_input_gtaw_filler_fno(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_GTAW_FILLER_F_NO
    await q.edit_message_text("🔧 F-Number فیلر GTAW را وارد کنید (مثال: F6):", reply_markup=_kb([]))
    return INPUT_GTAW_FILLER_F_NO


async def step_input_gtaw_filler_fno(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        raw = update.message.text.strip().upper().replace(" ", "")
        _d(context)["filler_gtaw"]["f_no"] = raw if raw.startswith("F") else f"F{raw}"
        _push(context, INPUT_GTAW_FILLER_F_NO)
        _d(context)["_current_state"] = INPUT_GTAW_FILLER_SFA
        await update.message.reply_text("📄 مشخصات SFA را وارد کنید (یا رد کنید):",
                                         reply_markup=_skip_kb("skip:gtaw_sfa"))
        return INPUT_GTAW_FILLER_SFA
    except Exception:
        logger.exception("خطا در step_input_gtaw_filler_fno")
        await _err(update, "F-Number فیلر GTAW")
        return ConversationHandler.END


async def _render_input_gtaw_filler_sfa(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_GTAW_FILLER_SFA
    await q.edit_message_text("📄 مشخصات SFA را وارد کنید (یا رد کنید):", reply_markup=_skip_kb("skip:gtaw_sfa"))
    return INPUT_GTAW_FILLER_SFA


async def step_input_gtaw_filler_sfa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _d(context)["filler_gtaw"]["sfa"] = update.message.text.strip()
        _push(context, INPUT_GTAW_FILLER_SFA)
        return await _after_gtaw_filler(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_gtaw_filler_sfa")
        await _err(update, "SFA فیلر GTAW")
        return ConversationHandler.END


async def step_skip_gtaw_sfa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _d(context)["filler_gtaw"]["sfa"] = None
    _push(context, INPUT_GTAW_FILLER_SFA)
    return await _after_gtaw_filler(query, context)


async def _after_gtaw_filler(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پس از فیلر GTAW: اگر SMAW هم فعال → الکترود SMAW؛ وگرنه گاز GTAW."""
    process = _d(context)["process"]
    if "SMAW" in process:
        return await _render_select_smaw_electrode(msg_or_query, context)
    return await _render_select_shielding_gas(msg_or_query, context)


# ══════════════════════════════════════════════════════════════════════════════
# QW-433 — انتخاب الکترود SMAW
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_smaw_electrode(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_SMAW_ELECTRODE
    await _render(msg_or_query, context, "🔧 الکترود SMAW را انتخاب کنید:", _smaw_electrode_kb())
    return SELECT_SMAW_ELECTRODE


async def step_select_smaw_electrode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        choice = query.data.split(":", 1)[1]
        _push(context, SELECT_SMAW_ELECTRODE)

        if choice == "MANUAL":
            _d(context)["_current_state"] = INPUT_SMAW_ELECTRODE_DESIGNATION
            await query.edit_message_text("✍️ نام/کد الکترود SMAW را وارد کنید:", reply_markup=_kb([]))
            return INPUT_SMAW_ELECTRODE_DESIGNATION

        electrode = next((e for e in SMAW_ELECTRODES if e["designation"] == choice), None)
        if not electrode:
            await query.edit_message_text("⚠️ الکترود یافت نشد.")
            return ConversationHandler.END
        _d(context)["filler_smaw"] = dict(electrode)
        return await _after_smaw_electrode(query, context)
    except Exception:
        logger.exception("خطا در step_select_smaw_electrode")
        await _err(update, "انتخاب الکترود SMAW")
        return ConversationHandler.END


async def _render_input_smaw_electrode_designation(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_SMAW_ELECTRODE_DESIGNATION
    await q.edit_message_text("✍️ نام/کد الکترود SMAW را وارد کنید:", reply_markup=_kb([]))
    return INPUT_SMAW_ELECTRODE_DESIGNATION


async def step_input_smaw_electrode_designation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _d(context).setdefault("filler_smaw", {})["designation"] = update.message.text.strip()
        _push(context, INPUT_SMAW_ELECTRODE_DESIGNATION)
        _d(context)["_current_state"] = INPUT_SMAW_ELECTRODE_F_NO
        await update.message.reply_text("🔧 F-Number الکترود SMAW را وارد کنید (مثال: F4):")
        return INPUT_SMAW_ELECTRODE_F_NO
    except Exception:
        logger.exception("خطا در step_input_smaw_electrode_designation")
        await _err(update, "نام الکترود SMAW")
        return ConversationHandler.END


async def _render_input_smaw_electrode_fno(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_SMAW_ELECTRODE_F_NO
    await q.edit_message_text("🔧 F-Number الکترود SMAW را وارد کنید (مثال: F4):", reply_markup=_kb([]))
    return INPUT_SMAW_ELECTRODE_F_NO


async def step_input_smaw_electrode_fno(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        raw = update.message.text.strip().upper().replace(" ", "")
        _d(context)["filler_smaw"]["f_no"] = raw if raw.startswith("F") else f"F{raw}"
        _push(context, INPUT_SMAW_ELECTRODE_F_NO)
        _d(context)["_current_state"] = INPUT_SMAW_ELECTRODE_SFA
        await update.message.reply_text("📄 مشخصات SFA را وارد کنید (یا رد کنید):",
                                         reply_markup=_skip_kb("skip:smaw_sfa"))
        return INPUT_SMAW_ELECTRODE_SFA
    except Exception:
        logger.exception("خطا در step_input_smaw_electrode_fno")
        await _err(update, "F-Number الکترود SMAW")
        return ConversationHandler.END


async def _render_input_smaw_electrode_sfa(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_SMAW_ELECTRODE_SFA
    await q.edit_message_text("📄 مشخصات SFA را وارد کنید (یا رد کنید):", reply_markup=_skip_kb("skip:smaw_sfa"))
    return INPUT_SMAW_ELECTRODE_SFA


async def step_input_smaw_electrode_sfa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _d(context)["filler_smaw"]["sfa"] = update.message.text.strip()
        _push(context, INPUT_SMAW_ELECTRODE_SFA)
        return await _after_smaw_electrode(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_smaw_electrode_sfa")
        await _err(update, "SFA الکترود SMAW")
        return ConversationHandler.END


async def step_skip_smaw_sfa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _d(context)["filler_smaw"]["sfa"] = None
    _push(context, INPUT_SMAW_ELECTRODE_SFA)
    return await _after_smaw_electrode(query, context)


async def _after_smaw_electrode(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    """پس از الکترود SMAW: اگر GTAW فعال بود یعنی فیلر GTAW از قبل انتخاب شده → گاز.
    اگر GTAW فعال نبود (SMAW تنها) → مستقیم الکتریکال SMAW (بدون گاز)."""
    process = _d(context)["process"]
    if "GTAW" in process:
        return await _render_select_shielding_gas(msg_or_query, context)
    return await _render_select_smaw_current(msg_or_query, context)


# ══════════════════════════════════════════════════════════════════════════════
# QW-408 — گاز محافظ (فقط اگر GTAW فعال باشد)
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_shielding_gas(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_SHIELDING_GAS
    await _render(msg_or_query, context, "💨 گاز محافظ GTAW را انتخاب کنید:", _shielding_gas_kb())
    return SELECT_SHIELDING_GAS


async def step_select_shielding_gas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        choice = query.data.split(":")[1]
        _push(context, SELECT_SHIELDING_GAS)

        if choice == "MANUAL":
            _d(context)["_current_state"] = INPUT_SHIELDING_GAS_MANUAL
            await query.edit_message_text("✍️ نوع گاز محافظ را وارد کنید:", reply_markup=_kb([]))
            return INPUT_SHIELDING_GAS_MANUAL

        _d(context)["shielding_gas"] = "Argon 99.9%"
        return await _render_select_gtaw_current(query, context)
    except Exception:
        logger.exception("خطا در step_select_shielding_gas")
        await _err(update, "گاز محافظ")
        return ConversationHandler.END


async def _render_input_shielding_gas_manual(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_SHIELDING_GAS_MANUAL
    await q.edit_message_text("✍️ نوع گاز محافظ را وارد کنید:", reply_markup=_kb([]))
    return INPUT_SHIELDING_GAS_MANUAL


async def step_input_shielding_gas_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _d(context)["shielding_gas"] = update.message.text.strip()
        _push(context, INPUT_SHIELDING_GAS_MANUAL)
        return await _render_select_gtaw_current(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_shielding_gas_manual")
        await _err(update, "گاز محافظ (دستی)")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# QW-409.4 — مشخصات الکتریکی GTAW
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_gtaw_current(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_GTAW_CURRENT
    await _render(msg_or_query, context, "⚡ نوع جریان GTAW را انتخاب کنید:", _current_kb("gcur"))
    return SELECT_GTAW_CURRENT


async def step_select_gtaw_current(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        current = query.data.split(":")[1]
        _d(context)["elec_gtaw"] = {"current": current, "polarity": None}
        _push(context, SELECT_GTAW_CURRENT)

        if current == "DC":
            _d(context)["_current_state"] = SELECT_GTAW_POLARITY
            await query.edit_message_text("⚡ قطبیت DC برای GTAW:", reply_markup=_polarity_kb("gpol"))
            return SELECT_GTAW_POLARITY

        return await _after_gtaw_electrical(query, context)
    except Exception:
        logger.exception("خطا در step_select_gtaw_current")
        await _err(update, "جریان GTAW")
        return ConversationHandler.END


async def _render_select_gtaw_polarity(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_GTAW_POLARITY
    await q.edit_message_text("⚡ قطبیت DC برای GTAW:", reply_markup=_polarity_kb("gpol"))
    return SELECT_GTAW_POLARITY


async def step_select_gtaw_polarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        polarity = query.data.split(":")[1]
        _d(context)["elec_gtaw"]["polarity"] = polarity
        _push(context, SELECT_GTAW_POLARITY)
        return await _after_gtaw_electrical(query, context)
    except Exception:
        logger.exception("خطا در step_select_gtaw_polarity")
        await _err(update, "قطبیت GTAW")
        return ConversationHandler.END


async def _after_gtaw_electrical(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    process = _d(context)["process"]
    if "SMAW" in process:
        return await _render_select_smaw_current(msg_or_query, context)
    return await _render_input_test_date(msg_or_query, context)


# ══════════════════════════════════════════════════════════════════════════════
# QW-409.4 — مشخصات الکتریکی SMAW
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_smaw_current(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_SMAW_CURRENT
    await _render(msg_or_query, context, "⚡ نوع جریان SMAW را انتخاب کنید:", _current_kb("scur"))
    return SELECT_SMAW_CURRENT


async def step_select_smaw_current(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        current = query.data.split(":")[1]
        _d(context)["elec_smaw"] = {"current": current, "polarity": None}
        _push(context, SELECT_SMAW_CURRENT)

        if current == "DC":
            _d(context)["_current_state"] = SELECT_SMAW_POLARITY
            await query.edit_message_text("⚡ قطبیت DC برای SMAW:", reply_markup=_polarity_kb("spol"))
            return SELECT_SMAW_POLARITY

        return await _render_input_test_date(query, context)
    except Exception:
        logger.exception("خطا در step_select_smaw_current")
        await _err(update, "جریان SMAW")
        return ConversationHandler.END


async def _render_select_smaw_polarity(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_SMAW_POLARITY
    await q.edit_message_text("⚡ قطبیت DC برای SMAW:", reply_markup=_polarity_kb("spol"))
    return SELECT_SMAW_POLARITY


async def step_select_smaw_polarity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        polarity = query.data.split(":")[1]
        _d(context)["elec_smaw"]["polarity"] = polarity
        _push(context, SELECT_SMAW_POLARITY)
        return await _render_input_test_date(query, context)
    except Exception:
        logger.exception("خطا در step_select_smaw_polarity")
        await _err(update, "قطبیت SMAW")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# تاریخ آزمون — پیش‌فرض امروز، امکان ورود دستی
# ══════════════════════════════════════════════════════════════════════════════

async def _render_input_test_date(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_TEST_DATE
    try:
        from utils.dates import today_jalali
        today_j = today_jalali()
    except Exception:
        today_j = None
    text = "📅 تاریخ آزمون را وارد کنید (فرمت: ۱۴۰۳/۰۶/۱۵):"
    kb_rows = []
    if today_j:
        text += f"\n\nامروز: {today_j}"
        kb_rows.append([("📅 استفاده از امروز", f"today:{today_j}")])
    await _render(msg_or_query, context, text, _kb(kb_rows))
    return INPUT_TEST_DATE


async def step_use_today_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        today_j = query.data.split(":", 1)[1]
        return await _process_test_date(query, context, today_j)
    except Exception:
        logger.exception("خطا در step_use_today_date")
        await _err(update, "تاریخ آزمون")
        return ConversationHandler.END


async def step_input_test_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        text = update.message.text.strip()
        ok, err = validate_jalali_date_str(text)
        if not ok:
            await update.message.reply_text(f"⚠️ {err or 'تاریخ نامعتبر است.'}\nدوباره وارد کنید:")
            return INPUT_TEST_DATE
        return await _process_test_date(update.message, context, text)
    except Exception:
        logger.exception("خطا در step_input_test_date")
        await _err(update, "تاریخ آزمون")
        return ConversationHandler.END


async def _process_test_date(msg_or_query, context: ContextTypes.DEFAULT_TYPE, jalali_text: str) -> int:
    try:
        gregorian = jalali_to_gregorian(jalali_text)
    except Exception:
        await _render(msg_or_query, context, "⚠️ تاریخ قابل تبدیل نیست. دوباره وارد کنید:", _kb([]))
        return INPUT_TEST_DATE

    _d(context)["test_date"] = gregorian
    _d(context)["test_date_j"] = jalali_text
    _push(context, INPUT_TEST_DATE)

    if _d(context)["joint_type"] == "GROOVE":
        return await _render_select_visual_groove(msg_or_query, context)
    return await _render_select_visual_fillet(msg_or_query, context)


# ══════════════════════════════════════════════════════════════════════════════
# Inspection Workflow — مسیر Groove: Visual → RT
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_visual_groove(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_VISUAL_GROOVE
    await _render(msg_or_query, context, "🔍 نتیجه بازرسی چشمی (Visual) را وارد کنید:",
                  _acc_rej_kb("visg"))
    return SELECT_VISUAL_GROOVE


async def step_select_visual_groove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        result = query.data.split(":")[1]
        _d(context)["visual_groove_result"] = result
        _push(context, SELECT_VISUAL_GROOVE)

        if result == "REJ":
            return await _finalize(query, context, "REJECTED")

        _d(context)["_current_state"] = SELECT_RT_RESULT
        await query.edit_message_text(
            "☢️ نتیجه رادیوگرافی (RT) را وارد کنید:",
            reply_markup=_acc_rej_kb("rt", extra=[("🕒 ثبت بعداً (Pending RT)", "rt:PENDING")]),
        )
        return SELECT_RT_RESULT
    except Exception:
        logger.exception("خطا در step_select_visual_groove")
        await _err(update, "بازرسی چشمی")
        return ConversationHandler.END


async def _render_select_rt(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_RT_RESULT
    await q.edit_message_text("☢️ نتیجه رادیوگرافی (RT) را وارد کنید:",
                               reply_markup=_acc_rej_kb("rt", extra=[("🕒 ثبت بعداً (Pending RT)", "rt:PENDING")]))
    return SELECT_RT_RESULT


async def step_select_rt_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        result = query.data.split(":")[1]
        _d(context)["rt_result"] = result
        _push(context, SELECT_RT_RESULT)

        if result == "ACC":
            return await _finalize(query, context, "QUALIFIED")
        elif result == "REJ":
            return await _finalize(query, context, "REJECTED")
        else:  # PENDING
            return await _finalize(query, context, "PENDING_RT")
    except Exception:
        logger.exception("خطا در step_select_rt_result")
        await _err(update, "نتیجه RT")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# Inspection Workflow — مسیر Fillet: Visual → Fracture → Macro
# (هر REJ در هر مرحله، فوراً به Rejected ختم می‌شود)
# ══════════════════════════════════════════════════════════════════════════════

async def _render_select_visual_fillet(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_VISUAL_FILLET
    await _render(msg_or_query, context, "🔍 نتیجه بازرسی چشمی (Visual) را وارد کنید:", _acc_rej_kb("visf"))
    return SELECT_VISUAL_FILLET


async def step_select_visual_fillet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        result = query.data.split(":")[1]
        _d(context)["visual_fillet_result"] = result
        _push(context, SELECT_VISUAL_FILLET)

        if result == "REJ":
            return await _finalize(query, context, "REJECTED")

        _d(context)["_current_state"] = SELECT_FRACTURE_RESULT
        await query.edit_message_text("🔨 نتیجه آزمون Fracture را وارد کنید:", reply_markup=_acc_rej_kb("frac"))
        return SELECT_FRACTURE_RESULT
    except Exception:
        logger.exception("خطا در step_select_visual_fillet")
        await _err(update, "بازرسی چشمی")
        return ConversationHandler.END


async def _render_select_fracture(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_FRACTURE_RESULT
    await q.edit_message_text("🔨 نتیجه آزمون Fracture را وارد کنید:", reply_markup=_acc_rej_kb("frac"))
    return SELECT_FRACTURE_RESULT


async def step_select_fracture(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        result = query.data.split(":")[1]
        _d(context)["fracture_result"] = result
        _push(context, SELECT_FRACTURE_RESULT)

        if result == "REJ":
            return await _finalize(query, context, "REJECTED")

        _d(context)["_current_state"] = SELECT_MACRO_RESULT
        await query.edit_message_text("🔬 نتیجه آزمون Macro را وارد کنید:", reply_markup=_acc_rej_kb("macro"))
        return SELECT_MACRO_RESULT
    except Exception:
        logger.exception("خطا در step_select_fracture")
        await _err(update, "نتیجه Fracture")
        return ConversationHandler.END


async def _render_select_macro(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SELECT_MACRO_RESULT
    await q.edit_message_text("🔬 نتیجه آزمون Macro را وارد کنید:", reply_markup=_acc_rej_kb("macro"))
    return SELECT_MACRO_RESULT


async def step_select_macro(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        result = query.data.split(":")[1]
        _d(context)["macro_result"] = result
        _push(context, SELECT_MACRO_RESULT)

        if result == "REJ":
            return await _finalize(query, context, "REJECTED")
        return await _finalize(query, context, "QUALIFIED")
    except Exception:
        logger.exception("خطا در step_select_macro")
        await _err(update, "نتیجه Macro")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# Finalize — اجرای Engine + تعیین مسیر ادامه بر اساس final_status
# ══════════════════════════════════════════════════════════════════════════════

def _build_engine_inputs(d: dict) -> dict:
    return {
        "process": d.get("process"),
        "specimen_type": d.get("specimen_type"),
        "joint_type": d.get("joint_type"),
        "test_position": d.get("test_position"),
        "pipe_od_mm": d.get("pipe_od_mm"),
        "base_metal_p_no": d.get("base_metal_p_no"),
        "base_metal_is_manual": d.get("base_metal_is_manual", False),
        "base_metal_thickness_mm": d.get("base_metal_thickness_mm"),
        "pass_count": d.get("pass_count"),
        "gtaw_deposit_thk_mm": d.get("gtaw_deposit_thk_mm"),
        "gtaw_pass_count": d.get("gtaw_pass_count"),
        "smaw_deposit_thk_mm": d.get("smaw_deposit_thk_mm"),
        "smaw_pass_count": d.get("smaw_pass_count"),
        "filler_smaw": d.get("filler_smaw"),
        "filler_gtaw": d.get("filler_gtaw"),
        "shielding_gas": d.get("shielding_gas"),
        "elec_smaw": d.get("elec_smaw"),
        "elec_gtaw": d.get("elec_gtaw"),
    }


async def _finalize(msg_or_query, context: ContextTypes.DEFAULT_TYPE, final_status: str) -> int:
    d = _d(context)
    d["final_status"] = final_status

    try:
        qr = _engine.calculate(_build_engine_inputs(d))
        d["qr_result"] = qr
    except QualificationValidationError as e:
        logger.warning("خطای اعتبارسنجی engine در finalize: %s", e)
        await _render(msg_or_query, context,
                      f"⚠️ *خطای محاسبه ASME:*\n{e}\n\nبرای اصلاح، از ⬅️ قبلی استفاده کنید.",
                      _kb([]))
        return _d(context).get("_current_state", SELECT_PROCESS)
    except Exception:
        logger.exception("خطای غیرمنتظره در engine")
        await _render(msg_or_query, context, "❌ خطای غیرمنتظره در محاسبه صلاحیت.", _kb([]))
        return ConversationHandler.END

    if final_status == "QUALIFIED":
        return await _render_input_expiry_date(msg_or_query, context)

    # برای Rejected و Pending RT: تاریخ انقضا از کاربر پرسیده نمی‌شود، ولی چون ستون
    # NOT NULL است و Pending RT برای فیلتر شدن در get_expiring_qualifications به یک
    # expiry_date نیاز دارد، مقدار پیش‌فرض محاسبه و بی‌صدا ذخیره می‌شود.
    d["expiry_date"] = compute_expiry_date(d["test_date"], validity_years=2)
    return await _render_final_summary(msg_or_query, context)


# ══════════════════════════════════════════════════════════════════════════════
# تاریخ انقضا و امضاکننده — فقط برای مسیر Qualified (بدون تغییر منطق نسبت به نسخه قبل)
# ══════════════════════════════════════════════════════════════════════════════

async def _render_input_expiry_date(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    d = _d(context)
    expiry = compute_expiry_date(d["test_date"], validity_years=2)
    d["expiry_date"] = expiry
    try:
        expiry_j = gregorian_to_jalali(expiry)
    except Exception:
        expiry_j = expiry
    _d(context)["_current_state"] = INPUT_EXPIRY_DATE
    await _render(msg_or_query, context,
                  f"✅ *Qualified*\n\n📅 تاریخ انقضای خودکار (۲ سال): *{expiry_j}*\n\n"
                  "آیا می‌خواهید تاریخ انقضا را دستی وارد کنید؟",
                  _skip_kb("skip:expiry"))
    return INPUT_EXPIRY_DATE


async def step_input_expiry_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        text = update.message.text.strip()
        ok, err = validate_jalali_date_str(text)
        if not ok:
            await update.message.reply_text(f"⚠️ {err or 'تاریخ نامعتبر.'}\nدوباره وارد کنید یا رد کنید:",
                                             reply_markup=_skip_kb("skip:expiry"))
            return INPUT_EXPIRY_DATE
        _d(context)["expiry_date"] = jalali_to_gregorian(text)
        _push(context, INPUT_EXPIRY_DATE)
        return await _render_input_signer_name(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_expiry_date")
        await _err(update, "تاریخ انقضا")
        return ConversationHandler.END


async def step_skip_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _push(context, INPUT_EXPIRY_DATE)
    return await _render_input_signer_name(query, context)


async def _render_input_signer_name(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_SIGNER_NAME
    await _render(msg_or_query, context, "✍️ نام امضاکننده مسئول را وارد کنید (یا رد کنید):",
                  _skip_kb("skip:signer_name"))
    return INPUT_SIGNER_NAME


async def step_input_signer_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _d(context)["signer_name"] = update.message.text.strip()
        _push(context, INPUT_SIGNER_NAME)
        return await _render_input_signer_title(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_signer_name")
        await _err(update, "نام امضاکننده")
        return ConversationHandler.END


async def step_skip_signer_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _d(context)["signer_name"] = None
    _push(context, INPUT_SIGNER_NAME)
    return await _render_input_signer_title(query, context)


async def _render_input_signer_title(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_SIGNER_TITLE
    await _render(msg_or_query, context, "💼 سمت امضاکننده را وارد کنید (یا رد کنید):",
                  _skip_kb("skip:signer_title"))
    return INPUT_SIGNER_TITLE


async def step_input_signer_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _d(context)["signer_title"] = update.message.text.strip()
        _push(context, INPUT_SIGNER_TITLE)
        return await _render_final_summary(update.message, context)
    except Exception:
        logger.exception("خطا در step_input_signer_title")
        await _err(update, "سمت امضاکننده")
        return ConversationHandler.END


async def step_skip_signer_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _d(context)["signer_title"] = None
    _push(context, INPUT_SIGNER_TITLE)
    return await _render_final_summary(query, context)


# ══════════════════════════════════════════════════════════════════════════════
# خلاصه نهایی و ذخیره — SHOW_FINAL_SUMMARY / CONFIRM_AND_SAVE
# ══════════════════════════════════════════════════════════════════════════════

async def _render_final_summary(msg_or_query, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = SHOW_FINAL_SUMMARY
    text = _fmt_final_summary(_d(context))
    await _render(msg_or_query, context, text, _confirm_save_kb())
    return CONFIRM_AND_SAVE


def _resolve_pass_count(d: dict) -> int:

    """pass_count ستون NOT NULL است؛ در حالت‌هایی که اصلاً پرسیده نشده

    (ضخامت<13mm، Fillet، یا GTAW+SMAW که مقدار در gtaw/smaw_pass_count جداست)

    باید یک مقدار معتبر جایگزین شود، نه None."""

    if d.get("pass_count") is not None:

        return d["pass_count"]

    if d.get("process") == "GTAW+SMAW":

        candidates = [c for c in (d.get("gtaw_pass_count"), d.get("smaw_pass_count")) if c is not None]

        if candidates:

            return max(candidates)

    return 1  # ضخامت<13mm یا Fillet — pass_count اصلاً essential variable نیست، مقدار حداقلی ثبت می‌شود





def _build_qualification_payload(context: ContextTypes.DEFAULT_TYPE, recorded_by: int) -> dict:
    d = _d(context)
    qr = d["qr_result"]

    extra_data = dict(qr.get("extra", {}))
    extra_data.update({
        "final_status": d.get("final_status"),
        "visual_groove_result": d.get("visual_groove_result"),
        "rt_result": d.get("rt_result"),
        "visual_fillet_result": d.get("visual_fillet_result"),
        "fracture_result": d.get("fracture_result"),
        "macro_result": d.get("macro_result"),
        "rt_status": "pending" if d.get("final_status") == "PENDING_RT" else "final",
        "welder_phone": d.get("new_welder_phone"),
        "welder_id_no": d.get("welder_id_no"),
        "coupon_no": d.get("coupon_no"),
        "wps_no": d.get("wps_no"),
        "wqt_no": d.get("wqt_no"),
        "base_metal_material": d.get("base_metal_material"),
        "contractor_id": d.get("contractor_id"),
        "contractor_name": d.get("contractor_name"),
    })

    # deposit_groove_mm: برای حالت تک‌فرآیندی معادل ضخامت فلز پایه در نظر گرفته می‌شود
    deposit_groove_mm = d.get("base_metal_thickness_mm")

    return {
        "welder_id": d["welder_id"],
        "project_id": d["project_id"],
        "recorded_by": recorded_by,
        "process": d["process"],
        "backing": "بدون backing",  # ستون CHECK باینری است؛ توضیح کامل در qr_backing ذخیره می‌شود
        "base_metal_p_no": d["base_metal_p_no"],
        "filler_f_no": qr["filler_f_no_display"],
        "filler_aws_class": None,
        "deposit_groove_mm": deposit_groove_mm,
        "deposit_fillet_mm": None,
        "pass_count": _resolve_pass_count(d),
        "specimen_type": d["specimen_type"],
        "pipe_od_mm": d.get("pipe_od_mm"),
        "test_position": d["test_position"],
        "joint_type": d["joint_type"],
        "test_date": d["test_date"],
        "qr_process": qr["qr_process"],
        "qr_backing": qr["qr_backing"],
        "qr_p_no": qr["qr_p_no"],
        "qr_thickness": qr["qr_thickness"],
        "qr_diameter": qr["qr_diameter"],
        "qr_position_groove": qr["qr_position_groove"],
        "qr_position_fillet": qr["qr_position_fillet"],
        "qr_f_no": qr["qr_f_no"],
        "expiry_date": d.get("expiry_date"),
        "signer_name": d.get("signer_name"),
        "signer_title": d.get("signer_title"),
        "extra_data": extra_data,
    }


async def step_confirm_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        action = query.data.split(":")[1]
        role = context.user_data.get("role", "operator")

        if action == "no":
            _clear(context)
            await query.edit_message_text("❌ ثبت لغو شد.", reply_markup=main_menu_keyboard(role))
            return ConversationHandler.END

        db_user = get_user_by_telegram_id(update.effective_user.id)

        if not db_user:

            await query.edit_message_text("❌ کاربر شما در سیستم ثبت نشده. با ادمین تماس بگیرید.")

            return ConversationHandler.END

        payload = _build_qualification_payload(context, db_user["id"])
        qual_id = add_qualification(payload)
        _d(context)["last_qual_id"] = qual_id
        logger.info("قابلیت صلاحیت ثبت شد: id=%d status=%s", qual_id, _d(context).get("final_status"))

        status_text = {
            "QUALIFIED": "✅ صلاحیت با موفقیت ثبت شد.",
            "REJECTED": "❌ آزمون رد شد و در سیستم ثبت گردید.",
            "PENDING_RT": "🕒 آزمون با وضعیت «در انتظار RT» ثبت شد.",
        }.get(_d(context).get("final_status"), "✅ ثبت شد.")

        await query.edit_message_text(f"{status_text}\n\nآیا فایل Excel تولید شود؟",
                                       reply_markup=_excel_kb())
        return ASK_GENERATE_EXCEL
    except Exception:
        logger.exception("خطا در step_confirm_and_save")
        await _err(update, "ذخیره نهایی")
        return ConversationHandler.END


async def step_ask_generate_excel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        action = query.data.split(":")[1]
        role = context.user_data.get("role", "operator")

        if action == "yes":
            qual_id = _d(context).get("last_qual_id")
            try:
                from engine.report_builder import build_wpq_excel
                excel_path = build_wpq_excel(qual_id)
                with open(excel_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=f,
                        filename=os.path.basename(excel_path),
                        caption=f"📊 گزارش WPQ صلاحیت #{qual_id}",
                    )
                await query.edit_message_text(
                    "✅ فایل Excel ارسال شد.\nبه منوی اصلی بازمی‌گردید.",
                    reply_markup=main_menu_keyboard(role),
                )
            except Exception:
                logger.exception("خطا در تولید Excel برای صلاحیت #%s", qual_id)
                await query.edit_message_text(
                    "❌ خطا در تولید فایل Excel. لطفاً با ادمین تماس بگیرید.",
                    reply_markup=main_menu_keyboard(role),
                )
        else:
            await query.edit_message_text("✅ ثبت کامل شد.\nبه منوی اصلی بازمی‌گردید.",
                                           reply_markup=main_menu_keyboard(role))
        _clear(context)
        return ConversationHandler.END
    except Exception:
        logger.exception("خطا در step_ask_generate_excel")
        await _err(update, "تولید Excel")
        return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# لغو سراسری (سازگار با نسخه قبل، برای /cancel)
# ══════════════════════════════════════════════════════════════════════════════

async def cancel_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear(context)
    role = context.user_data.get("role", "operator")
    if update.message:
        await update.message.reply_text("❌ ثبت آزمون لغو شد.", reply_markup=main_menu_keyboard(role))
    return ConversationHandler.END


async def cancel_via_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _clear(context)
    role = context.user_data.get("role", "operator")
    await query.edit_message_text("🏠 منوی اصلی:", reply_markup=main_menu_keyboard(role))
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# منوی مدیریت Pending RT — نقطه ورود مستقل: /pending_rt
# الگوی به‌روزرسانی: Deactivate + Reinsert (چون add_qualification تابع update ندارد)
# توافق‌شده با کاربر — qualification_id رکورد پس از نهایی‌شدن RT تغییر می‌کند.
# ══════════════════════════════════════════════════════════════════════════════

_PENDING_RT_LARGE_HORIZON_DAYS = 36500  # ~۱۰۰ سال — workaround برای «همه رکوردهای فعال»


def _fetch_pending_rt_qualifications() -> list[dict]:
    all_active = get_expiring_qualifications(days_ahead=_PENDING_RT_LARGE_HORIZON_DAYS)
    result = []
    for q in all_active:
        extra = q.get("extra_data") or {}
        if isinstance(extra, dict) and extra.get("rt_status") == "pending":
            result.append(q)
    return result


@require_auth
async def pending_rt_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        _clear(context)
        context.user_data["_pending_rt_ns"] = {}
        _d2 = context.user_data["_pending_rt_ns"]

        items = _fetch_pending_rt_qualifications()
        _d2["items"] = {q["id"]: q for q in items}

        text = f"🕒 *مدیریت Pending RT*\n\n{len(items)} آزمون در انتظار RT یافت شد.\n\nفیلتر (نام/کدملی/شناسه) یا «نمایش همه»:"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 نمایش همه", callback_data="prt:all")]])
        if update.message:
            await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        return PENDING_RT_FILTER
    except Exception:
        logger.exception("خطا در pending_rt_start")
        await _err(update, "شروع مدیریت Pending RT")
        return ConversationHandler.END


def _prt_kb(items: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for q in items:
        label = f"#{q['id']} — {q.get('test_position', '')} — {q.get('test_date', '')}"
        rows.append([InlineKeyboardButton(label, callback_data=f"prtsel:{q['id']}")])
    return InlineKeyboardMarkup(rows)


async def step_pending_rt_show_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        items = list(context.user_data["_pending_rt_ns"]["items"].values())
        if not items:
            await query.edit_message_text("✅ هیچ آزمون در انتظار RT وجود ندارد.")
            return ConversationHandler.END
        await query.edit_message_text(f"🕒 {len(items)} مورد:", reply_markup=_prt_kb(items))
        return PENDING_RT_SELECT
    except Exception:
        logger.exception("خطا در step_pending_rt_show_all")
        await _err(update, "نمایش لیست Pending RT")
        return ConversationHandler.END


async def step_pending_rt_filter_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        q_text = update.message.text.strip().lower()
        items = list(context.user_data["_pending_rt_ns"]["items"].values())
        filtered = [
            q for q in items
            if q_text in str(q.get("id", "")).lower()
            or q_text in str(q.get("welder_id", "")).lower()
        ]
        if not filtered:
            await update.message.reply_text("⚠️ موردی یافت نشد. دوباره فیلتر کنید یا /cancel بزنید:")
            return PENDING_RT_FILTER
        await update.message.reply_text(f"🕒 {len(filtered)} مورد:", reply_markup=_prt_kb(filtered))
        return PENDING_RT_SELECT
    except Exception:
        logger.exception("خطا در step_pending_rt_filter_text")
        await _err(update, "فیلتر Pending RT")
        return ConversationHandler.END


async def step_pending_rt_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        qid = int(query.data.split(":")[1])
        item = context.user_data["_pending_rt_ns"]["items"].get(qid)
        if not item:
            await query.edit_message_text("⚠️ رکورد یافت نشد.")
            return ConversationHandler.END

        context.user_data["_pending_rt_ns"]["selected"] = item
        await query.edit_message_text(
            f"🕒 آزمون #{qid}\nموقعیت: {item.get('test_position')}\nتاریخ: {item.get('test_date')}\n\n"
            "نتیجه نهایی RT را ثبت کنید:",
            reply_markup=_kb([[("✅ ACC", "prtres:ACC")], [("❌ REJ", "prtres:REJ")]], nav=False),
        )
        return PENDING_RT_RESULT
    except Exception:
        logger.exception("خطا در step_pending_rt_select")
        await _err(update, "انتخاب آزمون Pending RT")
        return ConversationHandler.END


async def step_pending_rt_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        query = update.callback_query
        await query.answer()
        result = query.data.split(":")[1]
        context.user_data["_pending_rt_ns"]["rt_final_result"] = result

        if result == "REJ":
            return await _pending_rt_finalize(query, context, "REJECTED")

        await query.edit_message_text("📅 تاریخ انقضا را وارد کنید (فرمت ۱۴۰۳/۰۶/۱۵) یا رد کنید:",
                                       reply_markup=_skip_kb("prtskip:expiry"))
        return PENDING_RT_EXPIRY
    except Exception:
        logger.exception("خطا در step_pending_rt_result")
        await _err(update, "نتیجه نهایی RT")
        return ConversationHandler.END


async def step_pending_rt_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        text = update.message.text.strip()
        ok, err = validate_jalali_date_str(text)
        if not ok:
            await update.message.reply_text(f"⚠️ {err or 'نامعتبر'}\nدوباره وارد کنید یا رد کنید:",
                                             reply_markup=_skip_kb("prtskip:expiry"))
            return PENDING_RT_EXPIRY
        context.user_data["_pending_rt_ns"]["expiry_date"] = jalali_to_gregorian(text)
        await update.message.reply_text("✍️ نام امضاکننده را وارد کنید (یا رد کنید):",
                                         reply_markup=_skip_kb("prtskip:signer_name"))
        return PENDING_RT_SIGNER_NAME
    except Exception:
        logger.exception("خطا در step_pending_rt_expiry")
        await _err(update, "تاریخ انقضا Pending RT")
        return ConversationHandler.END


async def step_pending_rt_skip_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    item = context.user_data["_pending_rt_ns"]["selected"]
    default_expiry = compute_expiry_date(item.get("test_date"), validity_years=2)
    context.user_data["_pending_rt_ns"]["expiry_date"] = default_expiry
    await query.edit_message_text("✍️ نام امضاکننده را وارد کنید (یا رد کنید):",
                                   reply_markup=_skip_kb("prtskip:signer_name"))
    return PENDING_RT_SIGNER_NAME


async def step_pending_rt_signer_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["_pending_rt_ns"]["signer_name"] = update.message.text.strip()
        await update.message.reply_text("💼 سمت امضاکننده را وارد کنید (یا رد کنید):",
                                         reply_markup=_skip_kb("prtskip:signer_title"))
        return PENDING_RT_SIGNER_TITLE
    except Exception:
        logger.exception("خطا در step_pending_rt_signer_name")
        await _err(update, "نام امضاکننده Pending RT")
        return ConversationHandler.END


async def step_pending_rt_skip_signer_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["_pending_rt_ns"]["signer_name"] = None
    await query.edit_message_text("💼 سمت امضاکننده را وارد کنید (یا رد کنید):",
                                   reply_markup=_skip_kb("prtskip:signer_title"))
    return PENDING_RT_SIGNER_TITLE


async def step_pending_rt_signer_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data["_pending_rt_ns"]["signer_title"] = update.message.text.strip()
        return await _pending_rt_finalize(update.message, context, "QUALIFIED")
    except Exception:
        logger.exception("خطا در step_pending_rt_signer_title")
        await _err(update, "سمت امضاکننده Pending RT")
        return ConversationHandler.END


async def step_pending_rt_skip_signer_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["_pending_rt_ns"]["signer_title"] = None
    return await _pending_rt_finalize(query, context, "QUALIFIED")


async def _pending_rt_finalize(msg_or_query, context: ContextTypes.DEFAULT_TYPE, final_status: str) -> int:
    """Deactivate رکورد Pending قدیمی + ایجاد رکورد جدید نهایی‌شده."""
    ns = context.user_data["_pending_rt_ns"]
    old = ns["selected"]
    role = context.user_data.get("role", "operator")

    set_qualification_inactive(old["id"])

    new_payload = dict(old)
    new_payload.pop("id", None)
    new_payload.pop("is_active", None)
    new_payload.pop("created_at", None)
    extra = dict(new_payload.get("extra_data") or {})
    extra["rt_status"] = "final"
    extra["rt_result"] = ns.get("rt_final_result")
    extra["final_status"] = final_status
    new_payload["extra_data"] = extra

    if final_status == "QUALIFIED":
        new_payload["expiry_date"] = ns.get("expiry_date")
        new_payload["signer_name"] = ns.get("signer_name")
        new_payload["signer_title"] = ns.get("signer_title")

    new_id = add_qualification(new_payload)
    logger.info("Pending RT نهایی شد: قدیمی #%d → جدید #%d (status=%s)", old["id"], new_id, final_status)

    text = (
        f"✅ نتیجه RT ثبت شد.\nرکورد جدید: #{new_id}\nوضعیت نهایی: "
        f"{'✅ Qualified' if final_status == 'QUALIFIED' else '❌ Rejected'}"
    )
    await _render(msg_or_query, context, text, main_menu_keyboard(role))
    context.user_data.pop("_pending_rt_ns", None)
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
# Rendererهای تکمیلی برای Navigation Stack (زنجیره اطلاعات تکمیلی جوشکار)
# ══════════════════════════════════════════════════════════════════════════════

async def _render_input_welder_id_no(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_WELDER_ID_NO
    await q.edit_message_text("🆔 Welder ID را وارد کنید (یا رد کنید):", reply_markup=_skip_kb("skip:welder_id_no"))
    return INPUT_WELDER_ID_NO


async def _render_input_coupon_no(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_COUPON_NO
    await q.edit_message_text("🧪 Coupon No را وارد کنید (یا رد کنید):", reply_markup=_skip_kb("skip:coupon_no"))
    return INPUT_COUPON_NO


async def _render_input_wps_no(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_WPS_NO
    await q.edit_message_text("📄 WPS No را وارد کنید (یا رد کنید):", reply_markup=_skip_kb("skip:wps_no"))
    return INPUT_WPS_NO


async def _render_input_wqt_no(q, context: ContextTypes.DEFAULT_TYPE) -> int:
    _d(context)["_current_state"] = INPUT_WQT_NO
    await q.edit_message_text("📃 WQT No را وارد کنید (یا رد کنید):", reply_markup=_skip_kb("skip:wqt_no"))
    return INPUT_WQT_NO


# ══════════════════════════════════════════════════════════════════════════════
# نگاشت State → Renderer — برای بازسازی صفحه هنگام ⬅️ قبلی
# ══════════════════════════════════════════════════════════════════════════════

_STATE_RENDERERS = {
    SELECT_PROJECT: _render_select_project,
    SELECT_CONTRACTOR: _render_select_contractor,
    SELECT_NEW_OR_RETEST: _render_new_or_retest,
    SEARCH_WELDER: _render_search_welder,
    SELECT_WELDER_FROM_SEARCH: _render_select_welder_from_search,
    INPUT_WELDER_NAME: _render_input_welder_name,
    INPUT_WELDER_NATIONAL_ID: _render_input_national_id,
    INPUT_WELDER_PHONE: _render_input_phone,
    INPUT_WELDER_PHOTO: _render_input_photo,
    ASK_ADDITIONAL_WELDER_INFO: _render_ask_additional_info,
    INPUT_WELDER_ID_NO: _render_input_welder_id_no,
    INPUT_COUPON_NO: _render_input_coupon_no,
    INPUT_WPS_NO: _render_input_wps_no,
    INPUT_WQT_NO: _render_input_wqt_no,
    SELECT_PROCESS: _render_select_process,
    SELECT_SPECIMEN_TYPE: _render_select_specimen,
    SELECT_JOINT_TYPE: _render_select_joint,
    INPUT_PIPE_OD: _render_input_pipe_od,
    SELECT_TEST_POSITION: _render_select_position,
    INPUT_BASE_METAL_THICKNESS: _render_input_base_thickness,
    INPUT_PASS_COUNT: _render_input_pass_count,
    INPUT_GTAW_DEPOSIT_THK: _render_input_gtaw_thk,
    INPUT_GTAW_PASS_COUNT: _render_input_gtaw_pass,
    INPUT_SMAW_DEPOSIT_THK: _render_input_smaw_thk,
    INPUT_SMAW_PASS_COUNT: _render_input_smaw_pass,
    SELECT_MATERIAL: _render_select_material,
    INPUT_MATERIAL_DESIGNATION: _render_input_material_designation,
    INPUT_MATERIAL_P_NO: _render_input_material_p_no,
    SELECT_GTAW_FILLER: _render_select_gtaw_filler,
    INPUT_GTAW_FILLER_DESIGNATION: _render_input_gtaw_filler_designation,
    INPUT_GTAW_FILLER_F_NO: _render_input_gtaw_filler_fno,
    INPUT_GTAW_FILLER_SFA: _render_input_gtaw_filler_sfa,
    SELECT_SMAW_ELECTRODE: _render_select_smaw_electrode,
    INPUT_SMAW_ELECTRODE_DESIGNATION: _render_input_smaw_electrode_designation,
    INPUT_SMAW_ELECTRODE_F_NO: _render_input_smaw_electrode_fno,
    INPUT_SMAW_ELECTRODE_SFA: _render_input_smaw_electrode_sfa,
    SELECT_SHIELDING_GAS: _render_select_shielding_gas,
    INPUT_SHIELDING_GAS_MANUAL: _render_input_shielding_gas_manual,
    SELECT_GTAW_CURRENT: _render_select_gtaw_current,
    SELECT_GTAW_POLARITY: _render_select_gtaw_polarity,
    SELECT_SMAW_CURRENT: _render_select_smaw_current,
    SELECT_SMAW_POLARITY: _render_select_smaw_polarity,
    INPUT_TEST_DATE: _render_input_test_date,
    SELECT_VISUAL_GROOVE: _render_select_visual_groove,
    SELECT_RT_RESULT: _render_select_rt,
    SELECT_VISUAL_FILLET: _render_select_visual_fillet,
    SELECT_FRACTURE_RESULT: _render_select_fracture,
    SELECT_MACRO_RESULT: _render_select_macro,
    INPUT_EXPIRY_DATE: _render_input_expiry_date,
    INPUT_SIGNER_NAME: _render_input_signer_name,
    INPUT_SIGNER_TITLE: _render_input_signer_title,
    CONFIRM_AND_SAVE: _render_final_summary,
}


# ══════════════════════════════════════════════════════════════════════════════
# ساخت ConversationHandler
# ══════════════════════════════════════════════════════════════════════════════

def get_registration_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(reg_start, pattern=r"^menu:register$"),
            CommandHandler("pending_rt", pending_rt_start),
            CallbackQueryHandler(pending_rt_start, pattern=r"^menu:pending_rt$"),
        ],
        states={
            SELECT_PROJECT: [CallbackQueryHandler(step_select_project, pattern=r"^proj:\d+$")],
            SELECT_CONTRACTOR: [CallbackQueryHandler(step_select_contractor, pattern=r"^cntr:\d+$")],
            SELECT_NEW_OR_RETEST: [CallbackQueryHandler(step_new_or_retest, pattern=r"^newretest:(new|retest)$")],
            SEARCH_WELDER: [MessageHandler(filters.TEXT, step_search_welder)],
            SELECT_WELDER_FROM_SEARCH: [CallbackQueryHandler(step_select_welder_from_search, pattern=r"^wldrsel:\d+$")],
            INPUT_WELDER_NAME: [MessageHandler(filters.TEXT, step_welder_name)],
            INPUT_WELDER_NATIONAL_ID: [MessageHandler(filters.TEXT, step_welder_national_id)],
            INPUT_WELDER_PHONE: [MessageHandler(filters.TEXT, step_welder_phone)],
            INPUT_WELDER_PHOTO: [
                MessageHandler(filters.PHOTO, step_welder_photo),
                CallbackQueryHandler(step_skip_photo, pattern=r"^skip:photo$"),
                MessageHandler(filters.TEXT, step_welder_photo),
            ],
            ASK_ADDITIONAL_WELDER_INFO: [CallbackQueryHandler(step_ask_additional_info, pattern=r"^addinfo:(yes|no)$")],
            INPUT_WELDER_ID_NO: [
                MessageHandler(filters.TEXT, step_input_welder_id_no),
                CallbackQueryHandler(step_skip_welder_id_no, pattern=r"^skip:welder_id_no$"),
            ],
            INPUT_COUPON_NO: [
                MessageHandler(filters.TEXT, step_input_coupon_no),
                CallbackQueryHandler(step_skip_coupon_no, pattern=r"^skip:coupon_no$"),
            ],
            INPUT_WPS_NO: [
                MessageHandler(filters.TEXT, step_input_wps_no),
                CallbackQueryHandler(step_skip_wps_no, pattern=r"^skip:wps_no$"),
            ],
            INPUT_WQT_NO: [
                MessageHandler(filters.TEXT, step_input_wqt_no),
                CallbackQueryHandler(step_skip_wqt_no, pattern=r"^skip:wqt_no$"),
            ],
            SELECT_PROCESS: [CallbackQueryHandler(step_select_process, pattern=r"^proc:")],
            SELECT_SPECIMEN_TYPE: [CallbackQueryHandler(step_select_specimen, pattern=r"^spec:")],
            SELECT_JOINT_TYPE: [CallbackQueryHandler(step_select_joint, pattern=r"^jtype:")],
            INPUT_PIPE_OD: [MessageHandler(filters.TEXT, step_input_pipe_od)],
            SELECT_TEST_POSITION: [CallbackQueryHandler(step_select_position, pattern=r"^pos:")],
            INPUT_BASE_METAL_THICKNESS: [MessageHandler(filters.TEXT, step_input_base_thickness)],
            INPUT_PASS_COUNT: [MessageHandler(filters.TEXT, step_input_pass_count)],
            INPUT_GTAW_DEPOSIT_THK: [MessageHandler(filters.TEXT, step_input_gtaw_thk)],
            INPUT_GTAW_PASS_COUNT: [MessageHandler(filters.TEXT, step_input_gtaw_pass)],
            INPUT_SMAW_DEPOSIT_THK: [MessageHandler(filters.TEXT, step_input_smaw_thk)],
            INPUT_SMAW_PASS_COUNT: [MessageHandler(filters.TEXT, step_input_smaw_pass)],
            SELECT_MATERIAL: [CallbackQueryHandler(step_select_material, pattern=r"^mat:")],
            INPUT_MATERIAL_DESIGNATION: [MessageHandler(filters.TEXT, step_input_material_designation)],
            INPUT_MATERIAL_P_NO: [MessageHandler(filters.TEXT, step_input_material_p_no)],
            SELECT_GTAW_FILLER: [CallbackQueryHandler(step_select_gtaw_filler, pattern=r"^gfil:")],
            INPUT_GTAW_FILLER_DESIGNATION: [MessageHandler(filters.TEXT, step_input_gtaw_filler_designation)],
            INPUT_GTAW_FILLER_F_NO: [MessageHandler(filters.TEXT, step_input_gtaw_filler_fno)],
            INPUT_GTAW_FILLER_SFA: [
                MessageHandler(filters.TEXT, step_input_gtaw_filler_sfa),
                CallbackQueryHandler(step_skip_gtaw_sfa, pattern=r"^skip:gtaw_sfa$"),
            ],
            SELECT_SMAW_ELECTRODE: [CallbackQueryHandler(step_select_smaw_electrode, pattern=r"^sele:")],
            INPUT_SMAW_ELECTRODE_DESIGNATION: [MessageHandler(filters.TEXT, step_input_smaw_electrode_designation)],
            INPUT_SMAW_ELECTRODE_F_NO: [MessageHandler(filters.TEXT, step_input_smaw_electrode_fno)],
            INPUT_SMAW_ELECTRODE_SFA: [
                MessageHandler(filters.TEXT, step_input_smaw_electrode_sfa),
                CallbackQueryHandler(step_skip_smaw_sfa, pattern=r"^skip:smaw_sfa$"),
            ],
            SELECT_SHIELDING_GAS: [CallbackQueryHandler(step_select_shielding_gas, pattern=r"^gas:")],
            INPUT_SHIELDING_GAS_MANUAL: [MessageHandler(filters.TEXT, step_input_shielding_gas_manual)],
            SELECT_GTAW_CURRENT: [CallbackQueryHandler(step_select_gtaw_current, pattern=r"^gcur:")],
            SELECT_GTAW_POLARITY: [CallbackQueryHandler(step_select_gtaw_polarity, pattern=r"^gpol:")],
            SELECT_SMAW_CURRENT: [CallbackQueryHandler(step_select_smaw_current, pattern=r"^scur:")],
            SELECT_SMAW_POLARITY: [CallbackQueryHandler(step_select_smaw_polarity, pattern=r"^spol:")],
            INPUT_TEST_DATE: [
                MessageHandler(filters.TEXT, step_input_test_date),
                CallbackQueryHandler(step_use_today_date, pattern=r"^today:"),
            ],
            SELECT_VISUAL_GROOVE: [CallbackQueryHandler(step_select_visual_groove, pattern=r"^visg:")],
            SELECT_RT_RESULT: [CallbackQueryHandler(step_select_rt_result, pattern=r"^rt:")],
            SELECT_VISUAL_FILLET: [CallbackQueryHandler(step_select_visual_fillet, pattern=r"^visf:")],
            SELECT_FRACTURE_RESULT: [CallbackQueryHandler(step_select_fracture, pattern=r"^frac:")],
            SELECT_MACRO_RESULT: [CallbackQueryHandler(step_select_macro, pattern=r"^macro:")],
            INPUT_EXPIRY_DATE: [
                MessageHandler(filters.TEXT, step_input_expiry_date),
                CallbackQueryHandler(step_skip_expiry, pattern=r"^skip:expiry$"),
            ],
            INPUT_SIGNER_NAME: [
                MessageHandler(filters.TEXT, step_input_signer_name),
                CallbackQueryHandler(step_skip_signer_name, pattern=r"^skip:signer_name$"),
            ],
            INPUT_SIGNER_TITLE: [
                MessageHandler(filters.TEXT, step_input_signer_title),
                CallbackQueryHandler(step_skip_signer_title, pattern=r"^skip:signer_title$"),
            ],
            CONFIRM_AND_SAVE: [CallbackQueryHandler(step_confirm_and_save, pattern=r"^confirm:(yes|no)$")],
            ASK_GENERATE_EXCEL: [CallbackQueryHandler(step_ask_generate_excel, pattern=r"^excel:")],
            PENDING_RT_FILTER: [
                CallbackQueryHandler(step_pending_rt_show_all, pattern=r"^prt:all$"),
                MessageHandler(filters.TEXT, step_pending_rt_filter_text),
            ],
            PENDING_RT_SELECT: [CallbackQueryHandler(step_pending_rt_select, pattern=r"^prtsel:\d+$")],
            PENDING_RT_RESULT: [CallbackQueryHandler(step_pending_rt_result, pattern=r"^prtres:(ACC|REJ)$")],
            PENDING_RT_EXPIRY: [
                MessageHandler(filters.TEXT, step_pending_rt_expiry),
                CallbackQueryHandler(step_pending_rt_skip_expiry, pattern=r"^prtskip:expiry$"),
            ],
            PENDING_RT_SIGNER_NAME: [
                MessageHandler(filters.TEXT, step_pending_rt_signer_name),
                CallbackQueryHandler(step_pending_rt_skip_signer_name, pattern=r"^prtskip:signer_name$"),
            ],
            PENDING_RT_SIGNER_TITLE: [
                MessageHandler(filters.TEXT, step_pending_rt_signer_title),
                CallbackQueryHandler(step_pending_rt_skip_signer_title, pattern=r"^prtskip:signer_title$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_registration),
            CallbackQueryHandler(cancel_via_menu, pattern=r"^menu:main$"),
            CallbackQueryHandler(nav_back, pattern=r"^nav:back$"),
            CallbackQueryHandler(nav_cancel_ask, pattern=r"^nav:cancel$"),
            CallbackQueryHandler(nav_cancel_yes, pattern=r"^nav:cancel_yes$"),
            CallbackQueryHandler(nav_cancel_no, pattern=r"^nav:cancel_no$"),
            CallbackQueryHandler(nav_home_ask, pattern=r"^nav:home$"),
            CallbackQueryHandler(nav_home_yes, pattern=r"^nav:home_yes$"),
            CallbackQueryHandler(nav_home_no, pattern=r"^nav:home_no$"),
        ],
        allow_reentry=True,
    )
