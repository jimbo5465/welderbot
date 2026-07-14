# WelderBot

WelderBot is a Telegram bot for managing **Welder Qualification Tests (WQT)** based on **ASME Section IX**.

The project is designed with a modular architecture so that each feature can be developed, tested and maintained independently.

---

# Main Features

- Welder Management
- WQT Registration
- Contractor Management
- Project Management
- Qualification History
- Excel Certificate Export
- Authentication & Authorization
- SQLite Database

---

# Technology Stack

- Python 3
- python-telegram-bot
- SQLite
- OpenPyXL
- Pillow
- jdatetime

---

# Project Structure

```
welderbot/
├── db/
├── engine/
├── forms/
├── handlers/
├── utils/
├── data/
├── media/
├── logs/
├── config.py
├── main.py
├── requirements.txt
└── welderbot.service
```

---

# Installation

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it:

Linux

```bash
source .venv/bin/activate
```

Windows

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Environment Variables

The project reads all sensitive values from Environment Variables.

Required variables:

```text
BOT_TOKEN
ADMIN_IDS
```

Optional:

```text
WELDERBOT_DEBUG
```

---

# Run

```bash
python main.py
```

---

# Dependencies

- python-telegram-bot
- openpyxl
- Pillow
- jdatetime

See:

```
requirements.txt
```

for exact versions.

---

# Architecture

Project architecture is documented in:

```
ARCHITECTURE.md
```

---

# Internal API

Stable APIs are documented in:

```
CONTRACTS.md
```

---

# Deployment

The project includes a ready-to-use systemd service.

```
welderbot.service
```

See:

```
RUN.md
```

for deployment instructions.

---

# License

## 🆕 فاز ۷ — خروجی Excel رسمی WPQ (در حال تکمیل)

بعد از ثبت هر آزمون WQT، ربات می‌تواند فایل Excel رسمی (فرم WPQ شرکت) را
خودکار پر کرده و برای اپراتور ارسال کند.

**وضعیت فعلی:** منطق اصلی و اتصال به ربات کامل و تست‌شده است.
دو مورد باقی‌مانده:
- تکمیل چند فیلد فرعی (`progression`, `shielding_gas`, `filler spec` و غیره)
  در `extra_data` هنگام ذخیره صلاحیت (نیاز به Patch در `_build_qualification_payload`)
- فیلد «ضخامت نمونه Plate» هنوز در دیتابیس ذخیره نمی‌شود

جزئیات کامل در `CONTRACTS.md` بخش «engine/report_builder.py».

## 🆕 فاز ۸ — سیستم دسترسی سلسله‌مراتبی (کامل)

سه سطح دسترسی، هرکدام محدود به یک محدوده مشخص:

| سطح | نام | محدوده |
|---|---|---|
| ۱ | مدیر پروژه | سراسری — می‌سازد/ویرایش/حذف پروژه |
| ۲ | مدیر پیمانکار | محدود به یک پروژه مشخص — پیمانکار اضافه/ویرایش/حذف می‌کند |
| ۳ | اپراتور | محدود به یک پیمانکار مشخص — فقط ثبت تست |

سطوح بالاتر، سطوح پایین‌تر را هم دارند (ارث‌بری). ادمین کل (`config.ADMIN_IDS`)
همیشه معادل سطح ۱ سراسری است.

**رابط کاربری:** از منوی اصلی → «👥 مدیریت کاربران». کاربر مقصد باید حداقل
یک‌بار `/start` زده باشد تا در فهرست انتخاب ظاهر شود (جدول `pending_users`).

**تغییر ساختاری مهم:** رابطه‌ی پروژه⇆پیمانکار از «یک‌به‌چند» به «چند‌به‌چند»
تغییر کرد (یک پروژه می‌تواند چند پیمانکار داشته باشد). جدول رابط:
`project_contractors`.

وضعیت: ✅ کامل و تست‌شده روی VPS.

Private Project

Copyright © Mohsen

All Rights Reserved.
