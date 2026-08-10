"""
engine/ncr_numbering.py
تولید شمارهٔ یکتای گزارش NCR بر اساس الگوی:

    <کد پروژه>-NCR-<سال شمسی>-<سریال>

مثال:
    PAR-NCR-1404-001

قوانین:
  - سال شمسی از jdatetime گرفته می‌شود.
  - سریال به ازای هر (پروژه، سال) از ۱ شروع و ۰-padding سه رقمی می‌شود.
  - یکتایی شماره با UNIQUE constraint جدول ncrs در سطح دیتابیس تضمین می‌شود.
  - این ماژول فقط از db.models و db.init می‌خواند؛ هیچ وابستگی به تلگرام ندارد.
"""

from __future__ import annotations

import jdatetime

from db.init import get_connection
from db.models import get_project_by_id


def jalali_year() -> int:
    """سال جاری شمسی."""
    return jdatetime.datetime.now().year


def project_code(project_id: int) -> str:
    """
    کد کوتاه پروژه برای شمارهٔ NCR.
    فعلاً از روی نام پروژه ساخته می‌شود (بدون فاصله، حداکثر ۱۲ کاراکتر).
    در آینده اگر پروژه ستون code بگیرد، همین‌جا جایگزین می‌شود — بقیهٔ
    ماژول‌ها بدون تغییر می‌مانند.
    """
    project = get_project_by_id(project_id)
    if project is None:
        raise ValueError(f"پروژه‌ای با id={project_id} یافت نشد.")
    name = project.get("name") or f"P{project_id}"
    code = "".join(ch for ch in name if ch.isalnum())[:12]
    return code.upper() if code else f"P{project_id}"


def max_serial_for_project(project_id: int) -> int:
    """
    بزرگ‌ترین سریال سال جاری برای این پروژه را از روی ncr_number های موجود
    (به فرمت <code>-NCR-<year>-<serial>) پیدا می‌کند. اگر هیچ رکوردی نباشد ۰.
    """
    rows = _fetch_existing_numbers(project_code(project_id))
    max_serial = 0
    for num in rows:
        try:
            serial = int(num.rsplit("-", 1)[-1])
            max_serial = max(max_serial, serial)
        except (ValueError, IndexError):
            continue
    return max_serial


def _fetch_existing_numbers(prefix_code: str) -> list[str]:
    pattern = f"{prefix_code}-NCR-{jalali_year()}-%"
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT ncr_number FROM ncrs WHERE ncr_number LIKE ?",
            (pattern,),
        ).fetchall()
    return [r["ncr_number"] for r in rows]


def generate_ncr_number(project_id: int) -> str:
    """
    شمارهٔ یکتای بعدی NCR را برای یک پروژه تولید می‌کند.

    مثال:
        generate_ncr_number(3)  # پروژهٔ «نیروگاه گازی»
        → "نیروگاهگازی-NCR-1404-001"

    فقط یک بار و قبل از submit صدا زده می‌شود؛ بعد از submit، ncr_number در
    دیتابیس ذخیره و همان شماره به Excel نوشته می‌شود (تغییر شماره پس از
    submit مجاز نیست).
    """
    code = project_code(project_id)
    serial = max_serial_for_project(project_id) + 1
    return f"{code}-NCR-{jalali_year()}-{serial:03d}"