"""
ماژول keyboards — سازنده‌های keyboard مشترک بین همه handlers.
تمام callback_data از پیشوندهای قفل‌شده CONTRACTS.md پیروی می‌کنند.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.auth import ROLE_ADMIN


# ══════════════════════════════════════════════════════════════════════════════
# منوی اصلی
# ══════════════════════════════════════════════════════════════════════════════

def main_menu_keyboard(role: str) -> InlineKeyboardMarkup:
    """
    keyboard منوی اصلی را بر اساس نقش کاربر می‌سازد.

    ورودی:
        role: 'admin' یا 'operator'

    خروجی:
        InlineKeyboardMarkup منوی اصلی
    """
    buttons = [
        [InlineKeyboardButton("📋 ثبت آزمون WQT",    callback_data="menu:register")],
        [InlineKeyboardButton("🔍 جستجوی جوشکار",    callback_data="menu:search")],
        [InlineKeyboardButton("👷 فهرست جوشکاران",   callback_data="menu:welders")],
        [InlineKeyboardButton("📊 گزارش صلاحیت‌ها",  callback_data="menu:report")],
    ]

    # دکمه‌های اختصاصی admin
    if role == ROLE_ADMIN:
        buttons.append([InlineKeyboardButton("⚙️ مدیریت پیمانکاران", callback_data="admin:contractors")])
        buttons.append([InlineKeyboardButton("👥 مدیریت کاربران",    callback_data="admin:users")])
        buttons.append([InlineKeyboardButton("🏗️ مدیریت پروژه‌ها",  callback_data="admin:projects")])

    return InlineKeyboardMarkup(buttons)


def back_to_main_keyboard() -> InlineKeyboardMarkup:
    """دکمه بازگشت به منوی اصلی."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu:main")]
    ])


# ══════════════════════════════════════════════════════════════════════════════
# keyboard‌های مرتبط با جوشکاران
# ══════════════════════════════════════════════════════════════════════════════

def welders_list_keyboard(welders: list[dict], page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    """
    keyboard فهرست جوشکاران با صفحه‌بندی.
    callback_data: wldr:ID (قفل‌شده در CONTRACTS.md)
    """
    start = page * page_size
    end   = start + page_size
    page_items = welders[start:end]

    buttons = []
    for w in page_items:
        label = f"👷 {w['full_name']} — {w['national_id']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"wldr:{w['id']}")])

    # دکمه‌های صفحه‌بندی
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"wldr_page:{page-1}"))
    if end < len(welders):
        nav.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"wldr_page:{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton("➕ افزودن جوشکار", callback_data="wldr_new:1"),
        InlineKeyboardButton("🏠 منو",            callback_data="menu:main"),
    ])
    return InlineKeyboardMarkup(buttons)


def welder_detail_keyboard(welder_id: int, role: str) -> InlineKeyboardMarkup:
    """
    keyboard جزئیات یک جوشکار — ویرایش و حذف فقط برای admin.
    """
    buttons = [
        [InlineKeyboardButton("📋 صلاحیت‌ها",    callback_data=f"wldr_quals:{welder_id}")],
    ]
    if role == ROLE_ADMIN:
        buttons.append([
            InlineKeyboardButton("✏️ ویرایش",       callback_data=f"wldr_edit:{welder_id}"),
            InlineKeyboardButton("🗑 حذف",           callback_data=f"wldr_del:{welder_id}"),
        ])
    buttons.append([InlineKeyboardButton("◀️ بازگشت", callback_data="menu:welders")])
    return InlineKeyboardMarkup(buttons)


def contractor_select_keyboard(contractors: list[dict]) -> InlineKeyboardMarkup:
    """
    keyboard انتخاب پیمانکار.
    callback_data: cntr:ID (قفل‌شده در CONTRACTS.md)
    """
    buttons = [
        [InlineKeyboardButton(c["name"], callback_data=f"cntr:{c['id']}")]
        for c in contractors
    ]
    buttons.append([InlineKeyboardButton("❌ انصراف", callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def confirm_keyboard(yes_data: str = "confirm:yes", no_data: str = "confirm:no") -> InlineKeyboardMarkup:
    """
    keyboard تأیید/لغو ساده.
    callback_data: confirm:yes / confirm:no (قفل‌شده در CONTRACTS.md)
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ بله",   callback_data=yes_data),
            InlineKeyboardButton("❌ خیر",   callback_data=no_data),
        ]
    ])


def skip_keyboard(skip_key: str) -> InlineKeyboardMarkup:
    """
    keyboard با دکمه رد کردن اختیاری.
    callback_data: skip:KEY (قفل‌شده در CONTRACTS.md)
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏭ رد کردن", callback_data=f"skip:{skip_key}")]
    ])


def welder_edit_fields_keyboard(welder_id: int) -> InlineKeyboardMarkup:
    """keyboard انتخاب فیلد برای ویرایش جوشکار."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 نام",          callback_data=f"edit:wldr_name:{welder_id}")],
        [InlineKeyboardButton("🏢 پیمانکار",     callback_data=f"edit:wldr_cntr:{welder_id}")],
        [InlineKeyboardButton("📅 تاریخ تولد",   callback_data=f"edit:wldr_bdate:{welder_id}")],
        [InlineKeyboardButton("🖼 عکس",          callback_data=f"edit:wldr_photo:{welder_id}")],
        [InlineKeyboardButton("◀️ بازگشت",       callback_data=f"wldr:{welder_id}")],
    ])
