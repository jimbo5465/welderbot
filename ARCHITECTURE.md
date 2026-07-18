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
