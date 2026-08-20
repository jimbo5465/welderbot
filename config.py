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

# مسیر ذخیره عکس‌های ثبت دانش (هر رکورد یک زیرپوشه به نام knowledge id دارد)
KN_PHOTO_PATH: str = os.path.join(_PROJECT_ROOT, "media", "kn_photos")

# مسیر خروجی فایل‌های PDF/Word پیش‌نویس DANA ثبت دانش
KN_OUTPUT_PATH: str = os.path.join(_PROJECT_ROOT, "media", "exports", "kn")

# ─── هوش مصنوعی (استخراج فیلدهای دانش از متن آزاد) ──────────────────────────
# کلاینت سازگار با OpenAI (پروتکل /v1/chat/completions).
# پیش‌فرض: OpenCode Go — https://opencode.ai/zen/go/v1
# اگر کلید یا مدل تنظیم نشده باشد، AI غیرفعال است و ربات به حالت
# «پرسش دستی همه فیلدها» برمی‌گردد (fallback امن).

# پایگاه آدرس OpenAI-سازگار
KNOWLEDGE_AI_BASE_URL: str = os.environ.get(
    "KNOWLEDGE_AI_BASE_URL", "https://opencode.ai/zen/go/v1"
)

# کلید: اول KNOWLEDGE_AI_API_KEY، سپس OPENCODE_GO_API_KEY (کلید OpenCode Go)
KNOWLEDGE_AI_API_KEY: str = os.environ.get(
    "KNOWLEDGE_AI_API_KEY",
    os.environ.get("OPENCODE_GO_API_KEY", ""),
)

# نام مدل — باید دقیقاً با یکی از شناسه‌های /v1/models نقطه انتهایی یکی باشد.
# خالی = AI غیرفعال (فهرست مدل‌ها:
#   curl -H "Authorization: Bearer $OPENCODE_API_KEY" https://opencode.ai/zen/go/v1/models
# )
KNOWLEDGE_AI_MODEL: str = os.environ.get("KNOWLEDGE_AI_MODEL", "")

# حداکثر زمان انتظار برای پاسخ مدل (ثانیه)
KNOWLEDGE_AI_TIMEOUT: float = float(os.environ.get("KNOWLEDGE_AI_TIMEOUT", "60"))

# ─── تبدیل گفتار به متن (STT) — Groq Whisper ─────────────────────────────────
# برای ثبت دانش: کاربر می‌تواند به‌جای تایپ، ویس بفرستد و ربات با
# whisper-large-v3-turbo روی Groq آن را به متن فارسی تبدیل می‌کند.
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
GROQ_STT_MODEL: str = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_STT_BASE_URL: str = os.environ.get("GROQ_STT_BASE_URL", "https://api.groq.com/openai/v1")

# ─── ایجاد خودکار پوشه‌های runtime در زمان import ────────────────────────────

def _ensure_dirs() -> None:
    """پوشه‌های runtime لازم را در صورت نبود ایجاد می‌کند."""
    for _dir in (
        os.path.dirname(DB_PATH),   # data/
        MEDIA_PATH,                  # media/photos/
        EXCEL_EXPORT_PATH,           # media/exports/
        NCR_PHOTO_PATH,              # media/ncr_photos/
        KN_PHOTO_PATH,               # media/kn_photos/
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
