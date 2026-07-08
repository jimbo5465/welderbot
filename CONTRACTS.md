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