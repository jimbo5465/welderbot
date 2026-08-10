"""
پیکربندی سراسری WelderBot.
تمام مقادیر حساس از متغیرهای محیطی خوانده می‌شوند.
این ماژول هیچ import داخلی از پروژه ندارد.
"""

import os
import sys

# ─── توکن ربات تلگرام ────────────────────────────────────────────────────────

# توکن از متغیر محیطی BOT_TOKEN خوانده می‌شود
BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
if not BOT_TOKEN:
    print("❌ خطا: متغیر محیطی BOT_TOKEN تنظیم نشده است. ربات راه‌اندازی نمی‌شود.", file=sys.stderr)
    # در زمان import خطا نمی‌دهیم تا تست‌های db بدون token کار کنند؛
    # main.py در فاز ۷ این مقدار را بررسی و در صورت خالی بودن sys.exit می‌کند.

# ─── شناسه ادمین‌ها ──────────────────────────────────────────────────────────

def _parse_admin_ids() -> set[int]:
    """
    مقدار ADMIN_IDS را از متغیر محیطی می‌خواند.
    فرمت انتظاری: رشته‌ای از شناسه‌های عددی جدا شده با کاما، مثال: '123456,789012'
    """
    raw = os.environ.get("ADMIN_IDS", "")
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            result.add(int(part))
    return result

# مجموعه شناسه‌های تلگرام ادمین‌ها
ADMIN_IDS: set[int] = _parse_admin_ids()

# ─── مسیرهای فایل‌سیستم ──────────────────────────────────────────────────────

# ریشه پروژه — پوشه‌ای که config.py در آن قرار دارد
_PROJECT_ROOT: str = os.path.dirname(os.path.abspath(__file__))

# مسیر فایل SQLite
DB_PATH: str = os.path.join(_PROJECT_ROOT, "data", "welderbot.db")

# مسیر ذخیره عکس‌های جوشکاران
MEDIA_PATH: str = os.path.join(_PROJECT_ROOT, "media", "photos")

# مسیر خروجی فایل‌های Excel گواهینامه
EXCEL_EXPORT_PATH: str = os.path.join(_PROJECT_ROOT, "media", "exports")

# مسیر خروجی فایل‌های Excel گزارش NCR
NCR_EXPORT_PATH: str = os.path.join(_PROJECT_ROOT, "media", "exports")

# مسیر ذخیره عکس‌های گزارش‌های NCR (هر گزارش یک زیرپوشه به نام ncr_id دارد)
NCR_PHOTO_PATH: str = os.path.join(_PROJECT_ROOT, "media", "ncr_photos")

# ─── ایجاد خودکار پوشه‌های runtime در زمان import ────────────────────────────

def _ensure_dirs() -> None:
    """پوشه‌های runtime لازم را در صورت نبود ایجاد می‌کند."""
    for _dir in (
        os.path.dirname(DB_PATH),   # data/
        MEDIA_PATH,                  # media/photos/
        EXCEL_EXPORT_PATH,           # media/exports/
        NCR_PHOTO_PATH,              # media/ncr_photos/
    ):
        os.makedirs(_dir, exist_ok=True)

_ensure_dirs()

# ─── تنظیمات کسب‌وکار ────────────────────────────────────────────────────────

# مدت اعتبار گواهینامه WQT به سال (ASME Sec. IX)
QUALIFICATION_VALIDITY_YEARS: int = 3

# ─── ثابت‌های ASME (مقادیر آستانه برای استفاده در engine فاز ۴) ─────────────

# حداقل ضخامت مجاز طبق QW-452.1(b)
ASME_MIN_THICKNESS_MM: float = 1.5

# آستانه ضخامت رسوب برای صلاحیت «بدون محدودیت» (QW-452.1(b))
ASME_UNLIMITED_THICKNESS_MM: float = 13.0

# حداقل تعداد پاس برای صلاحیت «بدون محدودیت» (QW-452.1(b))
ASME_UNLIMITED_PASS_COUNT: int = 3

# آستانه OD لوله برای صلاحیت کامل قطر (QW-452.3)
ASME_PIPE_FULL_QUAL_OD_MM: float = 73.0

# حداقل OD لوله (QW-452.3)
ASME_PIPE_MIN_OD_MM: float = 25.0
