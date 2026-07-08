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

---

# Development Rule

هر قابلیت جدید باید به صورت یک Handler مستقل پیاده‌سازی شود.

برای اضافه شدن یک Feature جدید، فقط ثبت Handler جدید در main.py مجاز است و ساختار معماری پروژه نباید تغییر کند.