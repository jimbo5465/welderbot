"""
ماژول keyboards — سازنده‌های keyboard مشترک بین همه handlers.
تمام callback_data از پیشوندهای قفل‌شده CONTRACTS.md پیروی می‌کنند.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.auth import ROLE_ADMIN
from handlers.auth import can_manage_projects, get_effective_level, LEVEL_CONTRACTOR_MANAGER


# ══════════════════════════════════════════════════════════════════════════════
# منوی اصلی
# ══════════════════════════════════════════════════════════════════════════════

def main_menu_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    """
    keyboard منوی اصلی را بر اساس سطح دسترسی مؤثر کاربر می‌سازد (فاز ۸).

    ورودی:
        telegram_id: شناسه تلگرام کاربر

    خروجی:
        InlineKeyboardMarkup منوی اصلی
    """
    buttons = [
        [InlineKeyboardButton("📋 ثبت آزمون WQT",    callback_data="menu:register")],
        [InlineKeyboardButton("🔍 جستجوی جوشکار",    callback_data="menu:search")],
        [InlineKeyboardButton("👷 فهرست جوشکاران",   callback_data="menu:welders")],
        [InlineKeyboardButton("📊 گزارش صلاحیت‌ها",  callback_data="menu:report")],
    ]

    # NCR — گزارش عدم انطباق (برای همه سطوح مجاز)
    buttons.append([InlineKeyboardButton("🚨 ثبت گزارش عدم انطباق (NCR)", callback_data="ncr:new")])

    is_level1 = can_manage_projects(telegram_id)

    # آیا کاربر حداقل در یک پروژه سطح ۲ دارد؟ (فاز ۱۲)

    # نکتهٔ باگ قبلی: get_effective_level(telegram_id) بدون project_id همیشه

    # None برای سطح ۲ برمی‌گرداند، چون تطبیق سطح ۲ در auth.py به project_id

    # مشخص نیاز دارد. باید همهٔ access_grants کاربر را مستقیم چک کنیم.

    from db.models import get_access_grants_by_telegram

    _grants = get_access_grants_by_telegram(telegram_id, active_only=True)

    is_level2_somewhere = any(g["level"] == LEVEL_CONTRACTOR_MANAGER for g in _grants)



    if is_level1:

        buttons.append([InlineKeyboardButton("🏗️ مدیریت پروژه‌ها",  callback_data="admin:projects")])

    if is_level1 or is_level2_somewhere:

        buttons.append([InlineKeyboardButton("⚙️ مدیریت پیمانکاران", callback_data="admin:contractors")])

    if is_level1:

        buttons.append([InlineKeyboardButton("👥 مدیریت کاربران",    callback_data="admin:users")])


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


# ══════════════════════════════════════════════════════════════════════════════
# keyboard‌های مدیریت دسترسی (فاز ۸)
# ══════════════════════════════════════════════════════════════════════════════

def pending_users_keyboard(users: list[dict]) -> InlineKeyboardMarkup:
    """keyboard انتخاب کاربر از فهرست pending_users."""
    buttons = [
        [InlineKeyboardButton(f"👤 {u['full_name']}", callback_data=f"pend:{u['telegram_id']}")]
        for u in users
    ]
    buttons.append([InlineKeyboardButton("❌ انصراف", callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def level_select_keyboard(allow_level1: bool) -> InlineKeyboardMarkup:
    """
    keyboard انتخاب سطح دسترسی.
    allow_level1: فقط سطح ۱ (ادمین کل) می‌تواند سطح ۱ یا ۲ معرفی کند؛
                  سطح ۲ فقط اجازه معرفی سطح ۳ دارد.
    """
    buttons = []
    if allow_level1:
        buttons.append([InlineKeyboardButton("۱ — مدیر پروژه (سراسری)", callback_data="lvl:1")])
        buttons.append([InlineKeyboardButton("۲ — مدیر پیمانکار (یک پروژه)", callback_data="lvl:2")])
    buttons.append([InlineKeyboardButton("۳ — اپراتور (یک پیمانکار)", callback_data="lvl:3")])
    buttons.append([InlineKeyboardButton("❌ انصراف", callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def project_select_keyboard(projects: list[dict]) -> InlineKeyboardMarkup:
    """keyboard انتخاب پروژه برای اعطای دسترسی سطح ۲ یا ۳."""
    buttons = [
        [InlineKeyboardButton(f"🏗️ {p['name']}", callback_data=f"gproj:{p['id']}")]
        for p in projects
    ]
    buttons.append([InlineKeyboardButton("❌ انصراف", callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def grant_contractor_select_keyboard(contractors: list[dict]) -> InlineKeyboardMarkup:
    """keyboard انتخاب پیمانکار برای اعطای دسترسی سطح ۳."""
    buttons = [
        [InlineKeyboardButton(f"🏢 {c['name']}", callback_data=f"gcntr:{c['id']}")]
        for c in contractors
    ]
    buttons.append([InlineKeyboardButton("❌ انصراف", callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)

# ══════════════════════════════════════════════════════════════════════════════
# این بلوک را به handlers/keyboards.py اضافه کنید (فایل فعلی در اختیارم نبود،
# پس این‌ها را به‌عنوان توابع مستقل و افزودنی نوشته‌ام — چیزی حذف/جایگزین نمی‌شود).
# فرض: از InlineKeyboardButton / InlineKeyboardMarkup استفاده می‌شود، مطابق
# الگوی welders_list_keyboard در همان فایل.
# ══════════════════════════════════════════════════════════════════════════════

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def projects_list_keyboard(projects: list[dict]) -> InlineKeyboardMarkup:
    """
    فهرست پروژه‌ها را به‌صورت دکمه نمایش می‌دهد.
    پروژهٔ خاتمه‌یافته با ⛔ و پروژهٔ فعال با 📁 مشخص می‌شود.
    بدون صفحه‌بندی — تعداد پروژه‌ها معمولاً کم است؛ اگر در آینده زیاد شد
    از الگوی welders_list_keyboard (page/wldr_page) پیروی کنید.
    """
    rows = []
    for p in projects:
        icon = "📁" if p.get("is_active") else "⛔"
        rows.append([
            InlineKeyboardButton(f"{icon} {p['name']}", callback_data=f"proj:{p['id']}")
        ])

    rows.append([InlineKeyboardButton("➕ پروژه جدید", callback_data="proj_new")])
    rows.append([InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu:main")])

    return InlineKeyboardMarkup(rows)


def project_detail_keyboard(project: dict) -> InlineKeyboardMarkup:
    """
    دکمه‌های عملیاتی جزئیات یک پروژه.
    اگر پروژه فعال است: ویرایش نام + خاتمه.
    اگر خاتمه‌یافته است: فعال‌سازی مجدد.
    """
    project_id = project["id"]
    rows = []

    if project.get("is_active"):
        rows.append([
            InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"proj_edit:{project_id}"),
        ])
        rows.append([
            InlineKeyboardButton("⛔ خاتمهٔ پروژه", callback_data=f"proj_term:{project_id}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton("♻️ فعال‌سازی مجدد", callback_data=f"proj_reactivate:{project_id}"),
        ])

    rows.append([InlineKeyboardButton("⬅️ بازگشت به فهرست پروژه‌ها", callback_data="admin:projects")])

    return InlineKeyboardMarkup(rows)


def management_submenu_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    """
    زیرمنوی «⚙️ مدیریت» — فعلاً فقط دکمهٔ مدیریت پروژه فعال است.
    مدیریت پیمانکار و مدیریت کاربران در فازهای بعدی به این تابع اضافه می‌شوند.

    ⚠️ نکته: این تابع به can_manage_projects نیاز دارد — import آن را از
    handlers.auth در بالای فایل keyboards.py اضافه کنید (در حال حاضر ممکن
    است keyboards.py به auth.py وابسته نباشد — این یک وابستگی جدید است،
    بررسی کنید که چرخهٔ import ایجاد نکند).
    """
    from handlers.auth import can_manage_projects  # noqa: E402  — نکتهٔ بالا را ببینید

    rows = []
    if can_manage_projects(telegram_id):
        rows.append([InlineKeyboardButton("📁 مدیریت پروژه", callback_data="menu:projects")])

    rows.append([InlineKeyboardButton("🏠 بازگشت به منو", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)

