# WelderBot Internal Contracts

Version: 1.0

---

# Purpose

این فایل قراردادهای داخلی پروژه WelderBot را تعریف می‌کند.

هدف آن حفظ سازگاری بین ماژول‌ها و جلوگیری از تغییرات ناسازگار در API های داخلی است.

هر توسعه‌دهنده (انسان یا AI) قبل از ایجاد Feature جدید باید این فایل را مطالعه کند.

---

# Development Rules

1. هیچ Feature نباید Feature دیگری را خراب کند.

2. توابع Public نباید بدون دلیل تغییر Signature داشته باشند.

3. دسترسی مستقیم به دیتابیس خارج از db/models.py مجاز نیست.

4. هر Feature جدید باید مستقل و قابل Commit باشد.

5. هر تغییر در Public API باید در این فایل ثبت شود.

---

# Stable Modules

| Module | Description |
|---------|-------------|
| db/models.py | Database Access Layer |
| engine/qualification.py | Qualification Engine |
| handlers/auth.py | Authentication |
| handlers/keyboards.py | Shared Telegram Keyboards |
| forms/wqt_excel.py | Excel Generator |

---

# Public APIs

## db/models.py

### User Management

- add_user()
- get_user_by_telegram_id()
- list_users()
- set_user_inactive()

---

### Contractor Management

- add_contractor()
- list_contractors()

---

### Project Management

- add_project()
- list_projects()

---

### Welder Management

- add_welder()
- get_welder_by_id()
- get_welder_by_national_id()
- list_welders_by_contractor()
- search_welders()
- update_welder()
- update_welder_photo()
- set_welder_inactive()

---

### Qualification Management

- add_qualification()
- get_qualification_by_id()
- list_qualifications_by_welder()
- get_expiring_qualifications()
- set_qualification_inactive()

---

### Reference Data

- list_materials()
- list_fillers()

---

# Internal APIs

توابع Private فقط داخل همان فایل استفاده می‌شوند و نباید توسط سایر ماژول‌ها فراخوانی شوند.

---

# Module Responsibilities

## db/

تمام عملیات مربوط به SQLite و CRUD.

---

## handlers/

مدیریت گفتگوهای تلگرام و ارتباط با کاربر.

---

## engine/

پیاده‌سازی منطق استاندارد ASME Section IX.

---

## forms/

تولید فایل‌های Excel.

---

## utils/

توابع عمومی مورد استفاده در کل پروژه.

---

# Dependency Rules

وابستگی مجاز:

handlers
↓
engine
↓
db

forms
↓
db

utils
↑
قابل استفاده در همه ماژول‌ها

---

# Update Policy

در صورت اضافه شدن Public API جدید، این فایل باید همزمان بروزرسانی شود.

## engine/report_builder.py (فاز ۷)

### build_wpq_excel(qualification_id: int) -> str
فایل Excel رسمی WPQ را از روی رکورد qualification در دیتابیس می‌سازد.
فقط از get_qualification_by_id و get_welder_by_id می‌خواند.
خروجی: مسیر مطلق فایل ذخیره‌شده در config.EXCEL_EXPORT_PATH

### کلیدهای اضافه‌شده به qualifications.extra_data (وضعیت: ⏳ در انتظار اعمال Patch)
این کلیدها باید در _build_qualification_payload اضافه شوند:
- filler_gtaw: dict {designation, f_no, sfa} یا None
- filler_smaw: dict {designation, f_no, sfa} یا None
- elec_gtaw: dict {current, polarity} یا None
- elec_smaw: dict {current, polarity} یا None
- shielding_gas: str یا None
- progression: str (از qr_result engine گرفته می‌شود)

### ⚠️ فیلد شناسایی‌شده ولی هنوز بدون منبع داده
"ضخامت نمونه Plate" (برای specimen_type=PLATE) در هیچ‌جای دیتابیس
ذخیره نمی‌شود — نیاز به بررسی در فاز بعدی.

## سیستم دسترسی (فاز ۸)

### db/models.py — توابع جدید
- `register_pending_user(telegram_id, full_name, username) -> None`
- `list_pending_users(exclude_telegram_ids=None) -> list[dict]`
- `add_access_grant(telegram_id, level, granted_by, project_id=None, contractor_id=None) -> int`
- `get_access_grants_by_telegram(telegram_id, active_only=True) -> list[dict]`
- `revoke_access_grant(grant_id) -> None`
- `list_grants_by_project(project_id) -> list[dict]`
- `link_project_contractor(project_id, contractor_id) -> None`
- `unlink_project_contractor(project_id, contractor_id) -> None`
- `list_contractors_by_project(project_id, active_only=True) -> list[dict]`
- `list_projects_by_contractor(contractor_id, active_only=True) -> list[dict]`

### db/models.py — امضای تغییریافته
- `add_project(name)` — دیگر `contractor_id` نمی‌گیرد (چند‌به‌چند شد)
- `list_projects(active_only=True)` — دیگر پارامتر `contractor_id` ندارد

### handlers/auth.py — توابع جدید
LEVEL_PROJECT_MANAGER = 1, LEVEL_CONTRACTOR_MANAGER = 2, LEVEL_OPERATOR = 3
get_effective_level(telegram_id, project_id=None, contractor_id=None) -> int|None
can_manage_projects(telegram_id) -> bool
can_manage_contractors(telegram_id, project_id) -> bool
can_select_contractor(telegram_id, project_id, contractor_id) -> bool
can_grant_level3(telegram_id, project_id) -> bool

### handlers/keyboards.py — تغییریافته
`main_menu_keyboard(telegram_id)` — دیگر `role` نمی‌گیرد، مستقیم `telegram_id`
می‌گیرد و خودش سطح را تشخیص می‌دهد.

فاز ۱۲ — دسترسی سطح ۲ به مدیریت پیمانکاران (کامل و تست‌شده روی VPS)

بدهی فنی شناسایی‌شده در فاز ۱۱ رفع شد: کاربر سطح ۲ اکنون می‌تواند از منوی
اصلی مستقیماً به فهرست پیمانکاران پروژهٔ خودش دسترسی داشته باشد (و از
همان‌جا درخواست خاتمهٔ همکاری بدهد — فلوی تأیید سطح ۱ که در فاز ۱۰ ساخته
شد، بدون تغییر).

باگ ریشه‌ای که پیدا و رفع شد

handlers/keyboards.py :: main_menu_keyboard از
get_effective_level(telegram_id) بدون project_id برای تشخیص «آیا
کاربر سطح ۲ است؟» استفاده می‌کرد. اما تطبیق سطح ۲ در
auth.py::get_effective_level ذاتاً به project_id مشخص نیاز دارد
(if project_id is not None and g["project_id"] == project_id) — بدون
آن همیشه None برمی‌گشت. نتیجه: دکمهٔ «⚙️ مدیریت پیمانکاران» هرگز برای
هیچ کاربر سطح ۲ ای نمایش داده نمی‌شد.

تغییرات


handlers/keyboards.py :: main_menu_keyboard — اکنون مستقیماً
get_access_grants_by_telegram را می‌خواند و وجود حداقل یک grant سطح ۲
فعال را چک می‌کند (صرف‌نظر از project_id خاص) تا دکمه را نشان دهد.
دکمهٔ «👥 مدیریت کاربران» صراحتاً level1-only باقی ماند (تصمیم عمدی:
اعطای دسترسی حساس است).
handlers/contractors.py :: contractor_management_entry — دیگر
_guard_level1 ندارد. سطح ۱ همهٔ پروژه‌ها (فعال+خاتمه‌یافته) را
می‌بیند؛ سطح ۲ فقط پروژه‌های فعالی که در آن‌ها get_my_project_ids
(فاز ۱۱) برایش project_id برمی‌گرداند.


بدون تغییر

show_contractors_menu, contractor_link_detail,
terminate_link_ask/execute و بقیهٔ توابع فاز ۱۰ از قبل با
can_manage_contractors(telegram_id, project_id) درست کار می‌کردند —
چون در آن نقطه project_id همیشه مشخص است. فقط نقطهٔ ورود
(contractor_management_entry) و نمایش دکمه در منو خراب بودند.

بدهی فنی باقی‌مانده (بدون تغییر نسبت به فاز ۱۱)


دو سیستم دسترسی موازی (role-based قدیمی + access_grants) هنوز هم‌زمان فعالند.
فیلد «ضخامت نمونه Plate» و چند کلید extra_data فاز ۷ هنوز ناتمام‌اند.



