# WelderBot Internal Contracts

---

## Purpose

این فایل قراردادهای داخلی پروژه WelderBot را تعریف می‌کند — برای حفظ
سازگاری بین ماژول‌ها و جلوگیری از تغییرات ناسازگار در APIهای داخلی.
هر توسعه‌دهنده (انسان یا AI) قبل از ایجاد feature جدید باید این فایل
را مطالعه کند.

---

## Development Rules

1. هیچ feature نباید feature دیگری را خراب کند.
2. توابع public نباید بدون دلیل تغییر signature داشته باشند.
3. دسترسی مستقیم به دیتابیس خارج از `db/models.py` مجاز نیست.
4. هر feature جدید باید مستقل و قابل commit باشد.
5. هر تغییر در public API باید هم‌زمان در این فایل ثبت شود.

---

## Stable Modules

| Module | Description |
|---|---|
| `db/models.py` | Database Access Layer |
| `engine/qualification.py` | Qualification Engine |
| `engine/report_builder.py` | WPQ Excel Builder |
| `handlers/auth.py` | Authentication & Access Control |
| `handlers/keyboards.py` | Shared Telegram Keyboards |
| `forms/wqt_excel.py` | Excel Generator |

---

## Module Responsibilities

- **db/** — تمام عملیات SQLite و CRUD.
- **handlers/** — مدیریت گفتگوهای تلگرام و ارتباط با کاربر.
- **engine/** — پیاده‌سازی منطق استاندارد ASME Section IX.
- **forms/** — تولید فایل‌های Excel.
- **utils/** — توابع عمومی مورد استفاده در کل پروژه.

## Dependency Rules
handlers
↓
engine
↓
db
forms
↓
db
utils ← قابل استفاده در همه‌ی ماژول‌ها
---

## Public APIs — db/models.py

### User Management
- `add_user()`
- `get_user_by_telegram_id()`
- `list_users()`
- `set_user_inactive()`

### Access Control
- `register_pending_user(telegram_id, full_name, username) -> None`
- `list_pending_users(exclude_telegram_ids=None) -> list[dict]`
- `add_access_grant(telegram_id, level, granted_by, project_id=None, contractor_id=None) -> int`
- `get_access_grants_by_telegram(telegram_id, active_only=True) -> list[dict]`
- `revoke_access_grant(grant_id) -> None`
- `list_grants_by_project(project_id) -> list[dict]`

### Project Management
- `add_project(name) -> int` — بدون `contractor_id` (رابطه چند‌به‌چند است)
- `list_projects(active_only=True) -> list[dict]` — بدون پارامتر `contractor_id`
- `get_project_by_id(project_id) -> dict | None`
- `update_project_name(project_id, name) -> None`
- `set_project_inactive(project_id) -> None` — soft delete
- `reactivate_project(project_id) -> None`
- `get_project_stats(project_id) -> dict` — `{active_contractors: int, active_qualifications: int}`

### Contractor Management
- `add_contractor()`
- `list_contractors()`
- `get_contractor_by_id(contractor_id) -> dict | None`
- `get_contractor_by_name(name) -> dict | None`
- `update_contractor_name(contractor_id, name) -> None` — تغییر **سراسری**، روی همه‌ی پروژه‌های آن پیمانکار اثر می‌گذارد؛ فقط سطح ۱ باید صدا بزند

### Project ⇆ Contractor Relationship (`project_contractors`)
- `link_contractor_to_project(project_id, contractor_id, linked_by, label=None) -> int` — هم برای لینک اول، هم برای الحاق مجدد بعد از خاتمه
- `get_link_by_id(link_id) -> dict | None`
- `list_contractor_links_by_project(project_id, statuses=None) -> list[dict]`
- `list_contractors_by_project(project_id, active_only=True) -> list[dict]`
- `list_projects_by_contractor(contractor_id, active_only=True) -> list[dict]`
- `update_link_label(link_id, label) -> None` — برچسب **محلیِ پروژه**، نه نام پیمانکار
- `terminate_link_direct(link_id, terminated_by) -> None` — فقط سطح ۱
- `request_terminate_link(link_id, requested_by) -> None` — سطح ۲
- `approve_terminate_link(link_id, approved_by) -> None` — فقط سطح ۱
- `reject_terminate_link(link_id, reason) -> None` — فقط سطح ۱
- `list_pending_termination_requests() -> list[dict]`
- `is_link_active(project_id, contractor_id) -> bool` — API آماده برای گیت‌کردن «ثبت فعالیت جدید» در ماژول‌های فعالیتی آینده (جوش/رنگ/فیتینگ)؛ فعلاً هیچ‌جا صدا زده نمی‌شود، فقط قرارداد است.

> **قانون:** هیچ‌کدام از عملیات پروژه/پیمانکار hard-delete نیستند. `set_project_inactive` فقط `is_active=0` می‌کند؛ رکوردهای وابسته‌ی `project_contractors` و `qualifications` دست‌نخورده باقی می‌مانند.
>
> **قانون داده:** یک جفت `(project_id, contractor_id)` می‌تواند چند رکورد تاریخی در `project_contractors` داشته باشد؛ فقط یک رکورد `status='active'` برای هر جفت مجاز است — تضمین‌شده با partial UNIQUE INDEX در دیتابیس، نه فقط منطق برنامه.

### Welder Management
- `add_welder()`
- `get_welder_by_id()`
- `get_welder_by_national_id()`
- `list_welders_by_contractor()`
- `search_welders()`
- `update_welder()`
- `update_welder_photo()`
- `set_welder_inactive()`

### Qualification Management
- `add_qualification()`
- `get_qualification_by_id()`
- `list_qualifications_by_welder()`
- `get_expiring_qualifications()`
- `set_qualification_inactive()`

### Reference Data
- `list_materials()`
- `list_fillers()`

---

## Public APIs — handlers/auth.py
LEVEL_PROJECT_MANAGER = 1
LEVEL_CONTRACTOR_MANAGER = 2
LEVEL_OPERATOR = 3
- `get_effective_level(telegram_id, project_id=None, contractor_id=None) -> int | None` — بدون context هرگز سطح ۲/۳ را تشخیص نمی‌دهد (طراحی عمدی؛ جزئیات در ARCHITECTURE.md)
- `can_manage_projects(telegram_id) -> bool`
- `can_manage_contractors(telegram_id, project_id) -> bool`
- `can_select_contractor(telegram_id, project_id, contractor_id) -> bool`
- `can_grant_level3(telegram_id, project_id) -> bool`
- `get_my_project_ids(telegram_id) -> list[int] | None` — `None` = سطح ۱ (بدون محدودیت)؛ `list` = سطح ۲/۳ (فقط این project_idها مجازند)
- `get_my_contractor_id_for_project(telegram_id, project_id) -> int | None` — `None` = سطح ۱ یا ۲ در این پروژه (همه‌ی پیمانکاران مجاز)؛ `int` = سطح ۳ (فقط این contractor_id مجاز)
- `get_role`, `is_admin`, `is_authenticated` — فقط از `get_effective_level` می‌خوانند؛ `access_grants` تنها منبع حقیقت برای تصمیمات دسترسی است. جدول `users` دیگر در مسیر تصمیم‌گیری دسترسی خوانده نمی‌شود (فقط برای ثبت خودکار ادمین و نمایش نام باقی مانده).

---

## Public APIs — handlers/keyboards.py

- `main_menu_keyboard(telegram_id)` — مستقیم `telegram_id` می‌گیرد و خودش سطح دسترسی را تشخیص می‌دهد (نه `role`)
- `projects_list_keyboard(projects: list[dict]) -> InlineKeyboardMarkup`
- `project_detail_keyboard(project: dict) -> InlineKeyboardMarkup`
- `management_submenu_keyboard(telegram_id: int) -> InlineKeyboardMarkup` — وابسته به `handlers.auth.can_manage_projects`؛ هنوز در جریان اصلی فعال نشده (نگاه کنید ARCHITECTURE.md بدهی فنی)

---

## Public APIs — engine/report_builder.py

### `build_wpq_excel(qualification_id: int) -> str`
فایل Excel رسمی WPQ را از روی رکورد qualification در دیتابیس می‌سازد.
فقط از `get_qualification_by_id` و `get_welder_by_id` می‌خواند.
خروجی: مسیر مطلق فایل ذخیره‌شده در `config.EXCEL_EXPORT_PATH`.

### کلیدهای `qualifications.extra_data` (وضعیت: ⏳ در انتظار Patch)
باید در `_build_qualification_payload` اضافه شوند:
- `filler_gtaw`: dict `{designation, f_no, sfa}` یا `None`
- `filler_smaw`: dict `{designation, f_no, sfa}` یا `None`
- `elec_gtaw`: dict `{current, polarity}` یا `None`
- `elec_smaw`: dict `{current, polarity}` یا `None`
- `shielding_gas`: str یا `None`
- `progression`: str (از qr_result engine گرفته می‌شود)

⚠️ فیلد «ضخامت نمونه Plate» (برای `specimen_type=PLATE`) در هیچ‌جای
دیتابیس ذخیره نمی‌شود — بدهی فنی باز، نیاز به بررسی منبع داده.

---

## Access Rules Summary

| عملیات | سطح ۱ | سطح ۲ |
|---|---|---|
| افزودن/الحاق مجدد پیمانکار | هر پروژه | فقط پروژه‌ی خودش |
| ویرایش `contractors.name` (سراسری) | ✅ | ❌ |
| ویرایش `label` (محلی) | ✅ | فقط لینک‌های پروژه‌ی خودش |
| خاتمه‌ی لینک | مستقیم | فقط درخواست (نیاز تأیید سطح ۱) |
| تأیید/رد درخواست خاتمه | ✅ | ❌ |

### اطلاع‌رسانی خاتمه‌ی همکاری
درخواست خاتمه‌ی سطح ۲ به همه‌ی `config.ADMIN_IDS` با پیام فوری تلگرام
(دکمه‌های تأیید/رد) ارسال می‌شود. نتیجه‌ی تصمیم سطح ۱ (تأیید یا رد + دلیل)
به `termination_requested_by` بازگردانده می‌شود. فرض: `chat_id == telegram_id`
برای چت خصوصی با ربات.

---

## Callback Data Registry

### Projects (`handlers/projects.py`)
| pattern | handler |
|---|---|
| `menu:projects` | `show_projects_menu` |
| `proj:<id>` | `project_detail_callback` |
| `proj_new` | `add_project_start` (entry point) |
| `proj_edit:<id>` | `edit_project_start` (entry point) |
| `proj_term:<id>` | `terminate_project_confirm` (entry point) |
| `proj_term_yes:<id>` | `terminate_project_execute` |
| `proj_reactivate:<id>` | `reactivate_project_callback` |

### Contractors (`handlers/contractors.py`)
| pattern | handler |
|---|---|
| `ctr_list:<project_id>` | `show_contractors_menu` |
| `ctr_detail:<link_id>` | `contractor_link_detail` |
| `ctr_add:<project_id>` | `add_contractor_start` (entry point) |
| `ctr_skip_label` | `add_contractor_label_skip` |
| `ctr_relink:<project_id>:<contractor_id>` | `relink_contractor_start` (entry point) |
| `ctr_label_edit:<link_id>` | `edit_label_start` (entry point) |
| `ctr_rename:<link_id>` | `rename_contractor_start` (entry point, فقط سطح ۱) |
| `ctr_term_ask:<link_id>` | `terminate_link_ask` |
| `ctr_term_yes:<link_id>` | `terminate_link_execute` |
| `ctr_approve:<link_id>` | `approve_termination` (فقط سطح ۱) |
| `ctr_reject_start:<link_id>` | `reject_termination_start` (entry point, فقط سطح ۱) |

⚠️ هر callback_data جدید باید قبل از merge با این جدول و با
`test_registration.py` / `access_management.py` چک شود تا تداخل الگو
پیش نیاید.

---

## Internal APIs

توابع private فقط داخل همان فایل استفاده می‌شوند و نباید توسط سایر
ماژول‌ها فراخوانی شوند.

---

## Known Open Technical Debt

- کلیدهای `extra_data` و فیلد «ضخامت نمونه Plate» در خروجی Excel WPQ
  هنوز ناتمام‌اند (نگاه کنید بخش `engine/report_builder.py` بالا).
- کاربر سطح ۲ صفحه‌ی UI مستقلی برای «پروژه‌های من» ندارد — فقط از طریق
  فرآیند ثبت آزمون به‌طور غیرمستقیم محدود می‌شود، ولی نمی‌تواند مستقیماً
  پروژه/پیمانکار خودش را از منو مدیریت کند (مثلاً درخواست خاتمه‌ی
  همکاری پیمانکار).
- `management_submenu_keyboard` هنوز در جریان اصلی فعال نشده.

---

## Update Policy

در صورت اضافه‌شدن public API جدید، این فایل باید هم‌زمان به‌روزرسانی شود.
