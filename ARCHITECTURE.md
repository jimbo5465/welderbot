# ARCHITECTURE.md

# WelderBot Architecture

Version: 1.0

---

# Project Goal

WelderBot یک ربات تلگرام برای مدیریت تست صلاحیت جوشکاران (Welder Qualification Test) مطابق ASME Section IX است.

معماری پروژه به صورت ماژولار طراحی شده تا هر Feature بتواند به صورت مستقل توسعه یابد.

---

# Architecture Overview

```
Telegram User
      │
      ▼
Application (main.py)
      │
      ▼
Handlers
      │
      ├──────────────► Engine
      │                  │
      │                  ▼
      │                 Database
      │
      └──────────────► Forms
```

---

# Module Responsibilities

## main.py

وظایف:

- راه‌اندازی Logging
- مقداردهی اولیه Database
- ساخت Telegram Application
- ثبت تمام Handler ها
- شروع Polling

این فایل نباید شامل:

- SQL
- منطق ASME
- تولید Excel
- منطق کسب‌وکار

باشد.

---

## handlers/

مسئول مدیریت ارتباط با کاربر از طریق Telegram.

وظایف:

- دریافت پیام‌ها
- مدیریت Conversation
- نمایش Keyboard
- اعتبارسنجی اولیه ورودی‌ها
- فراخوانی Engine یا Database

این پوشه نباید شامل:

- SQL
- محاسبات ASME

باشد.

---

## engine/

پیاده‌سازی قوانین ASME Section IX.

وظایف:

- محاسبات Qualification
- قوانین استاندارد
- تعیین محدوده صلاحیت

این ماژول نباید وابستگی به Telegram داشته باشد.

---

## db/

تنها لایه دسترسی به پایگاه داده.

تمام عملیات CRUD فقط در این پوشه انجام می‌شود.

هیچ Handler مجاز به اجرای مستقیم SQL نیست.

---

## forms/

تولید فایل‌های Excel.

این بخش فقط خروجی اکسل تولید می‌کند.

---

## utils/

توابع عمومی مورد استفاده کل پروژه.

---

## config.py

مدیریت تنظیمات پروژه.

تمام متغیرهای محیطی از این فایل خوانده می‌شوند.

---

# Startup Sequence

ترتیب اجرای ربات:

1. راه‌اندازی Logging

2. بررسی تنظیمات

3. مقداردهی اولیه Database

4. ساخت Telegram Application

5. ثبت تمام Handlers

6. شروع Polling

---

# Handler Registration Order

ترتیب ثبت Handler ها اهمیت دارد.

ثبت به ترتیب زیر انجام می‌شود:

1. Error Handler

2. Conversation Handlers

3. Command Handlers

4. CallbackQuery Handlers

5. Fallback Handlers

---

# Current Features

- Authentication
- Main Menu
- Welder Management
- WQT Registration
- Excel Export

---

# Dependency Rules

وابستگی مجاز:

main.py
↓
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


## 🆕 ماژول جدید: engine/report_builder.py (فاز ۷)

یک ماژول مستقل که فقط از `db.models` می‌خواند — هیچ وابستگی به context
مکالمه تلگرام ندارد. طبق همان قانون لایه‌بندی پروژه (`db ← engine`).

ورودی: `qualification_id` (عدد)
خروجی: مسیر فایل Excel تولیدشده

Template مرجع (فرم اصلاح‌شده با split شدن سلول‌های label/value):
`media/templates/WPQ_template.xlsx`

### ⚠️ بدهی فنی شناسایی‌شده (برای فیچرهای بعدی)
توابع کمکی UI مثل `_kb`, `_render`, `_nav_row` در حال حاضر داخل
`handlers/test_registration.py` تعریف شده‌اند. برای فیچرهای بعدی
(مدیریت پیمانکار، مدیریت پروژه) پیشنهاد می‌شود این توابع به یک فایل
مستقل `utils/telegram_ui.py` منتقل شوند تا هر فیچر جدید فقط به این
فایل مشترک وابسته باشد، نه مستقیم به فایل‌های handler دیگر.
---

# Development Rule

هر قابلیت جدید باید به صورت یک Handler مستقل پیاده‌سازی شود.

برای اضافه شدن یک Feature جدید، فقط ثبت Handler جدید در main.py مجاز است و ساختار معماری پروژه نباید تغییر کند.


## 🆕 سیستم دسترسی (فاز ۸)

### جداول جدید
- `access_grants` — هر ردیف یک دسترسی: `(telegram_id, level, project_id, contractor_id)`.
  سطح ۱: project_id و contractor_id هر دو NULL. سطح ۲: فقط project_id.
  سطح ۳: هر دو پر.
- `pending_users` — هر کسی که `/start` زده، صرف‌نظر از داشتن دسترسی.
- `project_contractors` — رابطه‌ی چند‌به‌چند پروژه⇆پیمانکار (جایگزین ستون
  حذف‌شده‌ی `projects.contractor_id`).

### منطق مرکزی: `handlers/auth.py`
توابع تصمیم‌گیری (`get_effective_level`, `can_manage_projects`,
`can_manage_contractors`, `can_select_contractor`, `can_grant_level3`) —
همه‌ی handlerهای جدید باید فقط از این توابع استفاده کنند، نه SQL مستقیم.

`get_role()` قدیمی (سیستم admin/operator) اصلاح شد تا کاربران فاز۸ (که فقط
در `access_grants` رکورد دارند، نه در `users`) را هم «ثبت‌شده» بشناسد.

### فایل جدید: `handlers/access_management.py`
ConversationHandler مستقل برای اعطای دسترسی. الگوی state machine ساده
(بدون پشته back/cancel، شبیه `welders.py`) — نه الگوی پیچیده‌ی
`test_registration.py`.


فاز ۱۲ — تکمیل نقاط ورود سطح ۲ (کامل، تست‌شده روی VPS)

درس این فاز

get_effective_level(telegram_id, project_id=None, contractor_id=None)
عمداً به‌گونه‌ای طراحی شده که بدون context (project_id/contractor_id)
نمی‌تواند سطح ۲ یا ۳ را تشخیص دهد — این طراحی درست است چون سطح ۲/۳ ذاتاً
scoped هستند. اما این یعنی هر کد جدیدی که بخواهد بپرسد «آیا این کاربر
اصلاً سطح ۲ هست، در هر پروژه‌ای؟» باید مستقیم access_grants را بخواند،
نه از get_effective_level بدون آرگومان استفاده کند — این دومی همیشه
None می‌دهد و خطای بی‌صدا (نه Exception، فقط دکمهٔ نامرئی) تولید می‌کند.
این یک الگوی خطای قابل‌تکرار است؛ برای فیچرهای آینده که «آیا کاربر سطح X
در هر جایی هست؟» می‌پرسند، همین الگو (خواندن مستقیم grants) باید تکرار
شود، نه فراخوانی بدون-context به get_effective_level.

### ⚠️ بدهی فنی باقی‌مانده
`handlers/projects.py` و `handlers/contractors.py` هنوز ساخته نشده‌اند.
باید دقیقاً از الگوی `handlers/welders.py` + `handlers/keyboards.py` پیروی
کنند، و برای گیت‌کردن دسترسی از `can_manage_projects` /
`can_manage_contractors` (فاز ۸) استفاده کنند.

## 🆕 فاز 09 — مدیریت پیمانکار و رابطهٔ پروژه⇆پیمانکار (کامل، در انتظار تست VPS)

### تصمیم معماری کلیدی: تفکیک «پیمانکار» از «رابطهٔ پروژه⇆پیمانکار»

پیمانکار (`contractors`) یک entity سراسری با نام یکتا در کل سیستم است.
وضعیت فعال/خاتمه‌یافته و برچسب نمایشی («الحاقیه»، «فاز ۲») به **رابطه**
(`project_contractors`) تعلق دارد، نه به خود پیمانکار — چون یک پیمانکار
می‌تواند هم‌زمان در چند پروژه با وضعیت‌های متفاوت فعال باشد. خاتمهٔ همکاری
در یک پروژه هرگز روی پروژه‌های دیگر همان پیمانکار اثر نمی‌گذارد.

نتیجهٔ این تصمیم: `project_contractors` دیگر یک جدول رابط سادهٔ many-to-many
نیست، بلکه خودش یک چرخهٔ حیات کامل دارد (فعال → در انتظار خاتمه → خاتمه‌یافته
→ [الحاق مجدد: رکورد جدید] ...).

### الگوی دومرحله‌ای درخواست/تأیید

خاتمهٔ همکاری توسط سطح ۲ بلافاصله اجرا نمی‌شود — درخواست ثبت می‌شود و
مدیر سراسری (سطح ۱) با پیام فوری تلگرام مطلع و باید تأیید یا رد کند. این
الگو (`pending_termination` state + notify + approve/reject) اولین نمونهٔ
یک فلوی «نیاز به تأیید بالادست» در پروژه است — اگر فیچرهای آینده به الگوی
مشابه نیاز داشتند (مثلاً حذف جوشکار توسط سطح ۲)، از همین ساختار
(`request_*` / `approve_*` / `reject_*` + notify) پیروی کنید.

### وابستگی به هیچ ماژول جوشکاری

طبق قانون توسعه‌پذیری پروژه (رشته‌های آینده: رنگ، مونتاژ، فیتینگ)،
`handlers/contractors.py` و توابع مرتبط در `db/models.py` فقط به
`projects`، `contractors`، `project_contractors` وابسته‌اند — هیچ ارجاعی
به `welders` یا `qualifications` ندارند. تابع `is_link_active(project_id,
contractor_id)` به‌عنوان API آماده برای گیت کردن «ثبت فعالیت جدید» در
هر ماژول فعالیتی آینده در نظر گرفته شده، ولی در فاز ۱۰ هنوز جایی صدا زده
نمی‌شود.

### بدهی فنی شناسایی‌شده

- گیت «فقط مشاهده/جستجو، بدون ثبت فعالیت جدید» برای پیمانکار
  `pending_termination`/`terminated` هنوز در `handlers/test_registration.py`
  اعمال نشده — باید در فاز بعدی با فراخوانی `is_link_active` اضافه شود.
- تابع `management_submenu_keyboard` (فاز ۹) هنوز فعال نشده — nesting منوی
  «⚙️ مدیریت» (پروژه + پیمانکار + کاربران زیر یک دکمه) به فاز بعد از تکمیل
  «مدیریت کاربران» موکول شده.


فاز ۱۱ — نقطهٔ واقعی اعمال دسترسی (کامل، تست‌شده روی VPS)

درس معماری این فاز

فاز‌های ۸، ۹ و ۱۰ زیرساخت سطح‌بندی دسترسی را کامل ساختند
(access_grants, get_effective_level, can_manage_projects,
can_manage_contractors)، اما هیچ‌کدام در مسیر واقعی کار روزمرهٔ
کاربر (ثبت آزمون WQT) استفاده نمی‌شدند — فقط در صفحات مدیریتی
(projects.py, contractors.py) که خودشان فیچرهای تازه‌ای بودند. یعنی
زیرساخت درست بود ولی نقطهٔ اعمالش (enforcement point) اشتباه انتخاب شده
بود. درس برای فیچرهای آینده: هر قابلیت جدید کنترل‌دسترسی باید همراه با
شناسایی صریح «کجا واقعاً استفاده می‌شود» تکمیل شود، نه فقط تعریف API.

الگوی enforcement که این فاز تثبیت کرد

get_my_project_ids(telegram_id) -> None | list[int]
get_my_contractor_id_for_project(telegram_id, project_id) -> None | int

هر دو الگوی یکسانی دارند: None = بدون محدودیت (سطح بالاتر)، مقدار
مشخص = محدودیت. فیچرهای آینده (مثلاً محدودسازی فهرست جوشکاران یا گزارش
صلاحیت بر اساس سطح کاربر) باید از همین الگو پیروی کنند، نه الگوی تازه‌ای
اختراع کنند.


فاز ۱۳ — یک منبع حقیقت برای دسترسی (کامل، تست‌شده روی VPS)

درس معماری

از فاز ۸ به بعد، پروژه دو مسیر موازی برای «کاربر کیست؟» داشت: مسیر
قدیمی (users + role) که در مسیرهای ورود اولیه (/start, /cancel)
استفاده می‌شد، و مسیر جدید (access_grants + سطح‌بندی) که در فیچرهای
تازه (فاز ۹ به بعد) استفاده می‌شد. باگ‌های فاز ۱۱ و ۱۲ (و این فاز)
همه از همین شکاف سرچشمه می‌گرفتند — یک تابع در یک مسیر می‌نوشت، تابع
دیگر در مسیر موازی می‌خواند.

درس برای آینده: وقتی یک مفهوم پایه (مثل «سطح دسترسی کاربر») بازطراحی
می‌شود، بازنویسی تابع مرکزی که همه به آن ارجاع می‌دهند (اینجا:
get_role) کافی است — لازم نیست همهٔ محل‌های صدازننده تغییر کنند، اگر
امضا و قرارداد خروجی ثابت بماند. تشخیص این نکته در فاز ۱۳ هزینهٔ
ریفکتور را از «ویرایش ۵ فایل» به «ویرایش ۱ فایل» رساند.

وضعیت فعلی معماری دسترسی

config.ADMIN_IDS ──┐
                    ├──> get_effective_level() ──> get_role()/is_admin()/is_authenticated()
access_grants ──────┘         │
                               └──> can_manage_projects()/can_manage_contractors()/
                                    get_my_project_ids()/get_my_contractor_id_for_project()

جدول users فقط برای نوشتن (ثبت خودکار ادمین) و نمایش نام باقی مانده،
دیگر در مسیر تصمیم‌گیری دسترسی نیست.
