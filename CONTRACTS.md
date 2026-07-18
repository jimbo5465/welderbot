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

## db/models.py — توابع جدید (فاز ۹: چرخهٔ حیات پروژه)

- `get_project_by_id(project_id: int) -> dict | None`
- `update_project_name(project_id: int, name: str) -> None`
- `set_project_inactive(project_id: int) -> None`
- `reactivate_project(project_id: int) -> None`
- `get_project_stats(project_id: int) -> dict`
  — خروجی: `{active_contractors: int, active_qualifications: int}`

قانون: هیچ‌کدام hard-delete نیستند. `set_project_inactive` فقط `is_active=0`
می‌کند؛ رکوردهای `project_contractors` و `qualifications` وابسته دست‌نخورده
باقی می‌مانند.

## handlers/auth.py — وابستگی مورد استفاده (بدون تغییر امضا)

`handlers/projects.py` از `can_manage_projects(telegram_id) -> bool` (تعریف‌شده
در فاز ۸) به‌عنوان تنها گیت مجوز استفاده می‌کند. اگر امضای این تابع تغییر کند،
فقط `_guard_level1` در `handlers/projects.py` باید به‌روزرسانی شود.

## handlers/keyboards.py — توابع جدید (فاز ۹)

- `projects_list_keyboard(projects: list[dict]) -> InlineKeyboardMarkup`
- `project_detail_keyboard(project: dict) -> InlineKeyboardMarkup`
- `management_submenu_keyboard(telegram_id: int) -> InlineKeyboardMarkup`
  — وابستگی جدید به `handlers.auth.can_manage_projects`؛ قبل از merge بررسی
    شود که چرخهٔ import بین keyboards.py و auth.py ایجاد نمی‌شود.

## handlers/projects.py — ماژول جدید (فاز ۹)

الگوی معماری مشابه `handlers/welders.py`. مسئول: ایجاد/ویرایش نام/خاتمه/
فعال‌سازی مجدد پروژه. فقط سطح ۱ (`can_manage_projects`). به هیچ ماژول
مخصوص جوشکاری وابسته نیست — طبق اصل توسعه‌پذیری پروژه به رشته‌های آینده
(رنگ، مونتاژ، فیتینگ)، `projects.py` صرفاً روی جدول `projects` کار می‌کند.

### callback_data های جدید ثبت‌شده در این فاز
| pattern | handler |
|---|---|
| `menu:projects` | `show_projects_menu` |
| `proj:<id>` | `project_detail_callback` |
| `proj_new` | `add_project_start` (entry point مکالمه) |
| `proj_edit:<id>` | `edit_project_start` (entry point مکالمه) |
| `proj_term:<id>` | `terminate_project_confirm` (entry point مکالمه) |
| `proj_term_yes:<id>` | `terminate_project_execute` |
| `proj_reactivate:<id>` | `reactivate_project_callback` |

⚠️ بررسی کنید این pattern‌ها با هیچ callback_data موجود در پروژه (مثلاً در
`test_registration.py` یا `access_management.py`) تداخل ندارند.


## فاز ۱۰ — مدیریت پیمانکار و رابطهٔ پروژه⇆پیمانکار

### تغییر ساختاری در جدول project_contractors

از کلید ترکیبی ساده به مدل چرخهٔ‌حیات‌دار ارتقا یافت (ستون‌های جدید: `id`
مستقل، `label`، `status`، `linked_by/at`، `termination_requested_by/at`،
`terminated_by/at`، `reject_reason`). یک جفت `(project_id, contractor_id)`
اکنون می‌تواند چند رکورد تاریخی داشته باشد؛ فقط یک رکورد `status='active'`
برای هر جفت مجاز است (تضمین‌شده با partial UNIQUE INDEX در دیتابیس، نه فقط
منطق برنامه). migration در `_migrate_project_contractors_lifecycle`.

### db/models.py — توابع جدید

- `get_contractor_by_id(contractor_id) -> dict | None`
- `get_contractor_by_name(name) -> dict | None`
- `update_contractor_name(contractor_id, name) -> None` — تغییر **سراسری**،
  روی همهٔ پروژه‌های آن پیمانکار اثر می‌گذارد. فقط سطح ۱ باید صدا بزند.
- `link_contractor_to_project(project_id, contractor_id, linked_by, label=None) -> int`
  — هم برای اولین لینک و هم برای الحاق مجدد بعد از خاتمه استفاده می‌شود
- `get_link_by_id(link_id) -> dict | None`
- `list_contractor_links_by_project(project_id, statuses=None) -> list[dict]`
- `update_link_label(link_id, label) -> None` — برچسب **محلیِ پروژه**، نه
  نام پیمانکار
- `terminate_link_direct(link_id, terminated_by) -> None` — فقط سطح ۱
- `request_terminate_link(link_id, requested_by) -> None` — سطح ۲
- `approve_terminate_link(link_id, approved_by) -> None` — فقط سطح ۱
- `reject_terminate_link(link_id, reason) -> None` — فقط سطح ۱
- `list_pending_termination_requests() -> list[dict]`
- `is_link_active(project_id, contractor_id) -> bool` — برای گیت کردن ثبت
  فعالیت جدید در ماژول‌های دیگر (فاز‌های بعدی: جوش/رنگ/فیتینگ). در فاز ۱۰
  جایی صدا زده نمی‌شود، فقط API آماده است.

### قوانین دسترسی (خلاصه)

| عملیات | سطح ۱ | سطح ۲ |
|---|---|---|
| افزودن/الحاق مجدد پیمانکار | هر پروژه | فقط پروژهٔ خودش |
| ویرایش `contractors.name` (سراسری) | ✅ | ❌ |
| ویرایش `label` (محلی) | ✅ | فقط لینک‌های پروژهٔ خودش |
| خاتمهٔ لینک | مستقیم | فقط درخواست (نیاز تأیید سطح ۱) |
| تأیید/رد درخواست خاتمه | ✅ | ❌ |

### handlers/contractors.py — ماژول جدید

الگوی معماری مشابه `handlers/projects.py`. به هیچ ماژول جوشکاری وابسته
نیست. از `handlers.auth.can_manage_contractors(telegram_id, project_id)` و
`can_manage_projects(telegram_id)` به‌عنوان تنها گیت‌های مجوز استفاده می‌کند.

### callback_data های جدید

| pattern | handler |
|---|---|
| `ctr_list:<project_id>` | `show_contractors_menu` |
| `ctr_detail:<link_id>` | `contractor_link_detail` |
| `ctr_add:<project_id>` | `add_contractor_start` (entry point) |
| `ctr_skip_label` | `add_contractor_label_skip` |
| `ctr_relink:<project_id>:<contractor_id>` | `relink_contractor_start` (entry point) |
| `ctr_label_edit:<link_id>` | `edit_label_start` (entry point) |
| `ctr_rename:<link_id>` | `rename_contractor_start` (entry point، فقط سطح ۱) |
| `ctr_term_ask:<link_id>` | `terminate_link_ask` |
| `ctr_term_yes:<link_id>` | `terminate_link_execute` |
| `ctr_approve:<link_id>` | `approve_termination` (فقط سطح ۱) |
| `ctr_reject_start:<link_id>` | `reject_termination_start` (entry point، فقط سطح ۱) |

### اطلاع‌رسانی

درخواست خاتمهٔ سطح ۲ به همهٔ `config.ADMIN_IDS` با پیام فوری تلگرام (دکمه‌های
تأیید/رد) ارسال می‌شود. نتیجهٔ تصمیم سطح ۱ (تأیید یا رد + دلیل) به
`termination_requested_by` بازگردانده می‌شود. فرض: `chat_id == telegram_id`
برای چت خصوصی با ربات.


فاز ۱۱ — محدودسازی واقعی دسترسی در فرآیند ثبت آزمون (کامل و تست‌شده روی VPS)

طی تست فاز ۱۰ مشخص شد که سطح‌بندی دسترسی (فاز ۸) در فرآیند ثبت آزمون WQT
(handlers/test_registration.py) هرگز واقعاً اعمال نمی‌شد — کاربر سطح ۲/۳
می‌توانست هر پروژه/پیمانکاری را ببیند و برایش تست ثبت کند. این فاز آن را
حل می‌کند.

handlers/auth.py — توابع جدید


get_my_project_ids(telegram_id) -> list[int] | None
خروجی None یعنی سطح ۱ (بدون محدودیت). خروجی list یعنی سطح ۲/۳ —
فقط همین project_id ها مجازند.
get_my_contractor_id_for_project(telegram_id, project_id) -> int | None
خروجی None یعنی سطح ۱ یا ۲ در این پروژه (همهٔ پیمانکاران مجاز).
خروجی int یعنی سطح ۳ — فقط همین contractor_id مجاز است.


handlers/test_registration.py — تغییرات


reg_start: فهرست پروژه‌ها با get_my_project_ids فیلتر می‌شود.
_render_select_contractor: فهرست پیمانکاران با
get_my_contractor_id_for_project فیلتر می‌شود. اگر کاربر سطح ۳ دقیقاً
یک پیمانکار مجاز دارد، این مرحله خودکار رد می‌شود (مستقیم به
_render_new_or_retest). اگر پیمانکار او در این پروژه دیگر active
نیست (خاتمه‌یافته)، پیام روشن نمایش داده می‌شود و مکالمه پایان می‌یابد.


باگ‌های جانبی که در همین فاز پیدا و رفع شدند


db/models.py :: list_contractors_by_project — فقط
contractors.is_active (پرچم سراسری) را چک می‌کرد، نه
project_contractors.status (وضعیت رابطه در همان پروژه، فاز ۱۰). نتیجه:
پیمانکار خاتمه‌یافته در یک پروژه هنوز قابل‌انتخاب برای ثبت تست بود.
اصلاح شد: اکنون هر دو شرط چک می‌شود.
handlers/menu.py :: main_menu_callback — tg_user فقط داخل شرط
if not role: تعریف می‌شد؛ وقتی role از قبل در session بود،
UnboundLocalError می‌داد. اصلاح شد: تعریف tg_user به ابتدای تابع
منتقل شد.


بدهی فنی شناسایی‌شده (حل‌نشده، برای فاز بعد)


کاربر سطح ۲ هیچ صفحهٔ UI برای «پروژه‌های من» ندارد — دکمه‌های
admin:projects و admin:contractors در منوی اصلی هر دو level1-only
هستند. سطح ۲ فقط از طریق فرآیند ثبت آزمون (که حالا فیلتر می‌شود) به‌طور
غیرمستقیم محدود است، ولی نمی‌تواند مستقیماً پروژه/پیمانکار خودش را از
منو مدیریت کند (مثلاً درخواست خاتمهٔ همکاری پیمانکار).
دو سیستم دسترسی موازی هنوز هم‌زمان فعالند: سیستم قدیمی role-based
(get_role, جدول users) و سیستم جدید سطح‌بندی‌شده
(get_effective_level, access_grants). فعلاً هر دو لازم‌اند (اولی
برای require_auth/require_admin قدیمی، دومی برای فاز ۹/۱۰/۱۱) ولی
یکی‌سازی آن‌ها به‌عنوان یک ریفکتور جداگانه در نظر گرفته شده، نه بخشی از
این فاز.


