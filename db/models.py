"""
ماژول models — تمام توابع CRUD و query روی پایگاه داده SQLite.
تمام امضاها از CONTRACTS.md قفل شده‌اند.
فقط از config و db.init import می‌کند.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from config import DB_PATH
from db.init import get_connection


def _now_str() -> str:
    """زمان جاری را به فرمت ISO-8601 برمی‌گرداند."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """یک sqlite3.Row را به dict تبدیل می‌کند؛ اگر None باشد None برمی‌گرداند."""
    if row is None:
        return None
    return dict(row)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    """لیستی از sqlite3.Row را به list[dict] تبدیل می‌کند."""
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# مدیریت کاربران (جدول users)
# ══════════════════════════════════════════════════════════════════════════════

def add_user(telegram_id: int, full_name: str, role: str) -> int:
    """
    کاربر جدید را در جدول users ثبت می‌کند.

    ورودی:
        telegram_id: شناسه یکتای تلگرام کاربر
        full_name:   نام کامل کاربر
        role:        نقش کاربر — 'admin' یا 'operator'

    خروجی:
        id ردیف جدید در جدول users

    خطا:
        sqlite3.IntegrityError اگر telegram_id تکراری باشد
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO users (telegram_id, full_name, role, is_active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (telegram_id, full_name, role, _now_str()),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    """
    کاربر را با شناسه تلگرام جستجو می‌کند.

    ورودی:
        telegram_id: شناسه تلگرام

    خروجی:
        dict شامل تمام فیلدهای جدول users، یا None اگر یافت نشد
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        return _row_to_dict(row)


def set_user_inactive(user_id: int) -> None:
    """
    کاربر را غیرفعال می‌کند (soft-delete: is_active = 0).

    ورودی:
        user_id: شناسه کاربر در جدول users
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_active = 0 WHERE id = ?",
            (user_id,),
        )
        conn.commit()


def list_users(active_only: bool = True) -> list[dict]:
    """
    فهرست کاربران را برمی‌گرداند.

    ورودی:
        active_only: اگر True باشد فقط کاربران فعال برگردانده می‌شوند

    خروجی:
        لیستی از dict‌های کاربر
    """
    with get_connection() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM users WHERE is_active = 1 ORDER BY id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY id"
            ).fetchall()
        return _rows_to_dicts(rows)


# ══════════════════════════════════════════════════════════════════════════════
# مدیریت پیمانکاران (جدول contractors)
# ══════════════════════════════════════════════════════════════════════════════

def add_contractor(name: str) -> int:
    """
    پیمانکار جدید اضافه می‌کند.

    ورودی:
        name: نام پیمانکار (باید یکتا باشد)

    خروجی:
        id ردیف جدید در جدول contractors

    خطا:
        sqlite3.IntegrityError اگر نام تکراری باشد
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO contractors (name, is_active, created_at)
            VALUES (?, 1, ?)
            """,
            (name, _now_str()),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def list_contractors(active_only: bool = True) -> list[dict]:
    """
    فهرست پیمانکاران را برمی‌گرداند.

    ورودی:
        active_only: اگر True باشد فقط پیمانکاران فعال برگردانده می‌شوند

    خروجی:
        لیستی از dict‌های پیمانکار
    """
    with get_connection() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM contractors WHERE is_active = 1 ORDER BY name"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM contractors ORDER BY name"
            ).fetchall()
        return _rows_to_dicts(rows)


# ══════════════════════════════════════════════════════════════════════════════
# مدیریت پروژه‌ها (جدول projects)
# ══════════════════════════════════════════════════════════════════════════════

def add_project(name: str, contractor_id: int) -> int:
    """
    پروژه جدید اضافه می‌کند.

    ورودی:
        name:          نام پروژه
        contractor_id: شناسه پیمانکار مربوط (FK → contractors.id)

    خروجی:
        id ردیف جدید در جدول projects

    خطا:
        sqlite3.IntegrityError اگر ترکیب (name, contractor_id) تکراری باشد
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects (name, contractor_id, is_active, created_at)
            VALUES (?, ?, 1, ?)
            """,
            (name, contractor_id, _now_str()),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def list_projects(
    contractor_id: int | None = None,
    active_only: bool = True,
) -> list[dict]:
    """
    فهرست پروژه‌ها را برمی‌گرداند.

    ورودی:
        contractor_id: اگر مشخص شود فقط پروژه‌های آن پیمانکار برگردانده می‌شوند
        active_only:   اگر True باشد فقط پروژه‌های فعال برگردانده می‌شوند

    خروجی:
        لیستی از dict‌های پروژه
    """
    with get_connection() as conn:
        # ساختار پویای query با parameterized placeholders
        conditions: list[str] = []
        params: list = []

        if active_only:
            conditions.append("is_active = 1")
        if contractor_id is not None:
            conditions.append("contractor_id = ?")
            params.append(contractor_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = conn.execute(
            f"SELECT * FROM projects {where} ORDER BY name",
            params,
        ).fetchall()
        return _rows_to_dicts(rows)


# ══════════════════════════════════════════════════════════════════════════════
# مدیریت جوشکاران (جدول welders)
# ══════════════════════════════════════════════════════════════════════════════

def add_welder(
    national_id: str,
    full_name: str,
    contractor_id: int,
    photo_path: str | None,
    birth_date: str | None,
) -> int:
    """
    جوشکار جدید ثبت می‌کند.

    ورودی:
        national_id:   کد ملی ۱۰ رقمی
        full_name:     نام کامل جوشکار
        contractor_id: شناسه پیمانکار (FK → contractors.id)
        photo_path:    مسیر نسبی عکس یا None
        birth_date:    تاریخ تولد به فرمت 'YYYY-MM-DD' میلادی یا None

    خروجی:
        id ردیف جدید در جدول welders

    خطا:
        sqlite3.IntegrityError اگر national_id تکراری باشد
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO welders
                (national_id, full_name, contractor_id, photo_path, birth_date, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (national_id, full_name, contractor_id, photo_path, birth_date, _now_str()),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def get_welder_by_national_id(national_id: str) -> dict | None:
    """
    جوشکار را با کد ملی جستجو می‌کند.

    ورودی:
        national_id: کد ملی ۱۰ رقمی

    خروجی:
        dict شامل تمام فیلدهای جدول welders، یا None اگر یافت نشد
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM welders WHERE national_id = ?",
            (national_id,),
        ).fetchone()
        return _row_to_dict(row)


def get_welder_by_id(welder_id: int) -> dict | None:
    """
    جوشکار را با شناسه داخلی جستجو می‌کند.

    ورودی:
        welder_id: شناسه در جدول welders

    خروجی:
        dict شامل تمام فیلدهای جدول welders، یا None اگر یافت نشد
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM welders WHERE id = ?",
            (welder_id,),
        ).fetchone()
        return _row_to_dict(row)


def list_welders_by_contractor(
    contractor_id: int,
    active_only: bool = True,
) -> list[dict]:
    """
    فهرست جوشکاران یک پیمانکار را برمی‌گرداند.

    ورودی:
        contractor_id: شناسه پیمانکار
        active_only:   اگر True باشد فقط جوشکاران فعال برگردانده می‌شوند

    خروجی:
        لیستی از dict‌های جوشکار
    """
    with get_connection() as conn:
        if active_only:
            rows = conn.execute(
                """
                SELECT * FROM welders
                WHERE contractor_id = ? AND is_active = 1
                ORDER BY full_name
                """,
                (contractor_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM welders WHERE contractor_id = ? ORDER BY full_name",
                (contractor_id,),
            ).fetchall()
        return _rows_to_dicts(rows)


def set_welder_inactive(welder_id: int) -> None:
    """
    جوشکار را غیرفعال می‌کند (soft-delete: is_active = 0).

    ورودی:
        welder_id: شناسه جوشکار در جدول welders
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE welders SET is_active = 0 WHERE id = ?",
            (welder_id,),
        )
        conn.commit()


def search_welders(query: str) -> list[dict]:
    """
    جوشکار را بر اساس نام یا کد ملی جستجو می‌کند (LIKE match).

    ورودی:
        query: رشته جستجو (حداقل ۲ کاراکتر پیشنهاد می‌شود)

    خروجی:
        لیستی از dict‌های جوشکار مطابق با query (فقط موارد فعال)
    """
    pattern = f"%{query}%"
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM welders
            WHERE is_active = 1
              AND (full_name LIKE ? OR national_id LIKE ?)
            ORDER BY full_name
            """,
            (pattern, pattern),
        ).fetchall()
        return _rows_to_dicts(rows)


# ══════════════════════════════════════════════════════════════════════════════
# مدیریت صلاحیت‌ها (جدول qualifications)
# ══════════════════════════════════════════════════════════════════════════════

def add_qualification(data: dict) -> int:
    """
    رکورد صلاحیت جدید (WQT) ثبت می‌کند.

    ورودی:
        data: دیکشنری شامل تمام ستون‌های جدول qualifications به جز id و created_at.

        کلیدهای اجباری:
            welder_id, project_id, recorded_by,
            process, backing, base_metal_p_no, filler_f_no,
            pass_count, specimen_type, test_position, joint_type, test_date,
            qr_process, qr_backing, qr_p_no, qr_thickness, qr_diameter,
            qr_position_groove, qr_position_fillet, qr_f_no,
            expiry_date

        کلیدهای اختیاری:
            filler_aws_class, deposit_groove_mm, deposit_fillet_mm,
            pipe_od_mm, signer_name, signer_title,
            extra_data (dict یا None — برای هر داده اضافی آینده)

        نکته: مقادیر list (qr_p_no, qr_position_groove, qr_position_fillet, qr_f_no)
              قبل از ذخیره به JSON string تبدیل می‌شوند.
              extra_data نیز اگر dict باشد به JSON تبدیل می‌شود.

    خروجی:
        id ردیف جدید در جدول qualifications
    """
    # تبدیل list‌ها و dict به JSON string برای ذخیره‌سازی
    _data = dict(data)
    # اطمینان از وجود تمام کلیدهای اختیاری — اگر نباشند None می‌شوند
    for optional in ("filler_aws_class", "deposit_groove_mm", "deposit_fillet_mm",
                     "pipe_od_mm", "signer_name", "signer_title", "extra_data"):
        if optional not in _data:
            _data[optional] = None
    for list_field in ("qr_p_no", "qr_position_groove", "qr_position_fillet", "qr_f_no"):
        if isinstance(_data.get(list_field), list):
            _data[list_field] = json.dumps(_data[list_field], ensure_ascii=False)
    # extra_data: اگر dict باشد به JSON تبدیل می‌شود
    if isinstance(_data.get("extra_data"), dict):
        _data["extra_data"] = json.dumps(_data["extra_data"], ensure_ascii=False)
    elif "extra_data" not in _data:
        _data["extra_data"] = None

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO qualifications (
                welder_id, project_id, recorded_by,
                process, backing, base_metal_p_no, filler_f_no, filler_aws_class,
                deposit_groove_mm, deposit_fillet_mm, pass_count,
                specimen_type, pipe_od_mm, test_position, joint_type, test_date,
                qr_process, qr_backing, qr_p_no, qr_thickness, qr_diameter,
                qr_position_groove, qr_position_fillet, qr_f_no,
                expiry_date, signer_name, signer_title,
                is_active, created_at, extra_data
            ) VALUES (
                :welder_id, :project_id, :recorded_by,
                :process, :backing, :base_metal_p_no, :filler_f_no, :filler_aws_class,
                :deposit_groove_mm, :deposit_fillet_mm, :pass_count,
                :specimen_type, :pipe_od_mm, :test_position, :joint_type, :test_date,
                :qr_process, :qr_backing, :qr_p_no, :qr_thickness, :qr_diameter,
                :qr_position_groove, :qr_position_fillet, :qr_f_no,
                :expiry_date, :signer_name, :signer_title,
                1, :created_at, :extra_data
            )
            """,
            {**_data, "created_at": _now_str()},
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def _deserialize_qualification(row: sqlite3.Row | None) -> dict | None:
    """
    یک ردیف qualifications را به dict تبدیل می‌کند.
    فیلدهای JSON string را به list باز می‌گرداند.
    """
    if row is None:
        return None
    d = dict(row)
    for list_field in ("qr_p_no", "qr_position_groove", "qr_position_fillet", "qr_f_no"):
        if isinstance(d.get(list_field), str):
            try:
                d[list_field] = json.loads(d[list_field])
            except (json.JSONDecodeError, TypeError):
                d[list_field] = []
    # extra_data: اگر JSON string باشد به dict تبدیل می‌شود
    if isinstance(d.get("extra_data"), str):
        try:
            d["extra_data"] = json.loads(d["extra_data"])
        except (json.JSONDecodeError, TypeError):
            d["extra_data"] = {}
    elif d.get("extra_data") is None:
        d["extra_data"] = {}
    return d


def get_qualification_by_id(qualification_id: int) -> dict | None:
    """
    یک رکورد صلاحیت را با شناسه داخلی برمی‌گرداند.
    فیلدهای qr_* از JSON string به list تبدیل می‌شوند.

    ورودی:
        qualification_id: شناسه در جدول qualifications

    خروجی:
        dict شامل تمام فیلدهای qualifications، یا None اگر یافت نشد
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM qualifications WHERE id = ?",
            (qualification_id,),
        ).fetchone()
        return _deserialize_qualification(row)


def list_qualifications_by_welder(
    welder_id: int,
    active_only: bool = True,
) -> list[dict]:
    """
    فهرست تمام صلاحیت‌های یک جوشکار را برمی‌گرداند.
    فیلدهای qr_* از JSON string به list تبدیل می‌شوند.

    ورودی:
        welder_id:   شناسه جوشکار
        active_only: اگر True باشد فقط صلاحیت‌های فعال برگردانده می‌شوند

    خروجی:
        لیستی از dict‌های صلاحیت (جدیدترین اول)
    """
    with get_connection() as conn:
        if active_only:
            rows = conn.execute(
                """
                SELECT * FROM qualifications
                WHERE welder_id = ? AND is_active = 1
                ORDER BY created_at DESC
                """,
                (welder_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM qualifications
                WHERE welder_id = ?
                ORDER BY created_at DESC
                """,
                (welder_id,),
            ).fetchall()
        return [_deserialize_qualification(r) for r in rows]  # type: ignore[misc]


def get_expiring_qualifications(days_ahead: int = 30) -> list[dict]:
    """
    صلاحیت‌هایی که ظرف days_ahead روز آینده منقضی می‌شوند را برمی‌گرداند.
    تاریخ به فرمت میلادی 'YYYY-MM-DD' مقایسه می‌شود.

    ورودی:
        days_ahead: تعداد روزهای آینده برای بررسی انقضا (پیش‌فرض ۳۰)

    خروجی:
        لیستی از dict‌های صلاحیت رو به انقضا، مرتب بر اساس expiry_date
    """
    today = datetime.now().date()
    deadline = today + timedelta(days=days_ahead)
    today_str = today.isoformat()          # 'YYYY-MM-DD'
    deadline_str = deadline.isoformat()    # 'YYYY-MM-DD'

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM qualifications
            WHERE is_active = 1
              AND expiry_date >= ?
              AND expiry_date <= ?
            ORDER BY expiry_date ASC
            """,
            (today_str, deadline_str),
        ).fetchall()
        return [_deserialize_qualification(r) for r in rows]  # type: ignore[misc]


def set_qualification_inactive(qualification_id: int) -> None:
    """
    صلاحیت را غیرفعال می‌کند (soft-delete: is_active = 0).

    ورودی:
        qualification_id: شناسه رکورد صلاحیت
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE qualifications SET is_active = 0 WHERE id = ?",
            (qualification_id,),
        )
        conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
# متریال و فیلر (جداول materials و fillers)
# ══════════════════════════════════════════════════════════════════════════════

def list_materials(active_only: bool = True) -> list[dict]:
    """
    فهرست P-Numberهای فعال را از جدول materials برمی‌گرداند.

    ورودی:
        active_only: اگر True باشد فقط موارد فعال برگردانده می‌شوند

    خروجی:
        لیستی از dict‌های متریال شامل id, p_number, description, is_active
    """
    with get_connection() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM materials WHERE is_active = 1 ORDER BY p_number"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM materials ORDER BY p_number"
            ).fetchall()
        return _rows_to_dicts(rows)


def list_fillers(active_only: bool = True) -> list[dict]:
    """
    فهرست F-Numberهای فعال را از جدول fillers برمی‌گرداند.

    ورودی:
        active_only: اگر True باشد فقط موارد فعال برگردانده می‌شوند

    خروجی:
        لیستی از dict‌های فیلر شامل id, f_number, aws_class, description, is_active
    """
    with get_connection() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM fillers WHERE is_active = 1 ORDER BY f_number"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM fillers ORDER BY f_number"
            ).fetchall()
        return _rows_to_dicts(rows)


# ══════════════════════════════════════════════════════════════════════════════
# تست یکپارچه end-to-end
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import tempfile, os
    import json as _json

    # دیتابیس موقت برای تست
    tmp = tempfile.mktemp(suffix=".db")
    import config as _cfg
    from db.init import init_db

    _orig_path = _cfg.DB_PATH
    _cfg.DB_PATH = tmp

    print("=" * 60)
    print("🔬 تست یکپارچه لایه db")
    print("=" * 60)

    # ساخت جداول
    init_db()
    print("✅ init_db() اجرا شد.")

    # ثبت کاربر ادمین
    uid = add_user(telegram_id=100001, full_name="علی محمدی", role="admin")
    print(f"✅ کاربر ثبت شد — id={uid}")
    user = get_user_by_telegram_id(100001)
    print(f"   نقش: {user['role']} | فعال: {user['is_active']}")

    # ثبت پیمانکار
    cid = add_contractor("شرکت فولاد ساز")
    print(f"✅ پیمانکار ثبت شد — id={cid}")

    # ثبت پروژه
    pid = add_project("پروژه پالایشگاه شمال", cid)
    print(f"✅ پروژه ثبت شد — id={pid}")

    # ثبت جوشکار
    wid = add_welder(
        national_id="0123456789",
        full_name="رضا کریمی",
        contractor_id=cid,
        photo_path=None,
        birth_date="1370-05-15",
    )
    print(f"✅ جوشکار ثبت شد — id={wid}")
    w = get_welder_by_national_id("0123456789")
    print(f"   نام: {w['full_name']} | پیمانکار: {w['contractor_id']}")

    # جستجوی جوشکار
    results = search_welders("کریمی")
    print(f"✅ جستجو: {len(results)} نتیجه یافت شد.")

    # ثبت صلاحیت با تمام ۸ فیلد qr_*
    qdata = {
        "welder_id":          wid,
        "project_id":         pid,
        "recorded_by":        uid,
        "process":            "GTAW",
        "backing":            "بدون backing",
        "base_metal_p_no":    "P1",
        "filler_f_no":        "F6",
        "filler_aws_class":   "ER308L",
        "deposit_groove_mm":  14.0,
        "deposit_fillet_mm":  None,
        "pass_count":         3,
        "specimen_type":      "PIPE",
        "pipe_od_mm":         114.0,
        "test_position":      "6G",
        "joint_type":         "GROOVE",
        "test_date":          "2024-03-10",
        # ۸ فیلد qr_* (از engine در فاز ۴ محاسبه می‌شوند، اینجا dummy)
        "qr_process":         "GTAW",
        "qr_backing":         "فقط بدون backing",
        "qr_p_no":            ["P1", "P3", "P4"],
        "qr_thickness":       "1.5mm to unlimited",
        "qr_diameter":        "≥ 25mm",
        "qr_position_groove": ["1G", "2G", "3G", "4G", "5G", "6G"],
        "qr_position_fillet": [],
        "qr_f_no":            ["F6"],
        "expiry_date":        "2027-03-10",
        "signer_name":        "مهندس احمدی",
        "signer_title":       "مسئول جوش",
    }
    qid = add_qualification(qdata)
    print(f"✅ صلاحیت ثبت شد — id={qid}")

    # خواندن صلاحیت
    q = get_qualification_by_id(qid)
    print(f"   qr_p_no (list): {q['qr_p_no']}")
    print(f"   qr_thickness: {q['qr_thickness']}")
    print(f"   qr_f_no (list): {q['qr_f_no']}")

    # فهرست صلاحیت‌های جوشکار
    ql = list_qualifications_by_welder(wid)
    print(f"✅ فهرست صلاحیت‌ها: {len(ql)} مورد")

    # صلاحیت‌های رو به انقضا (تست با ۵ سال آینده)
    expiring = get_expiring_qualifications(days_ahead=5 * 365)
    print(f"✅ صلاحیت‌های رو به انقضا (۵ سال): {len(expiring)} مورد")

    # P-Numberها و F-Numberها
    mats = list_materials()
    fills = list_fillers()
    print(f"✅ P-Numberها: {[m['p_number'] for m in mats]}")
    print(f"✅ F-Numberها: {[f['f_number'] for f in fills]}")

    # پاکسازی
    _cfg.DB_PATH = _orig_path
    os.remove(tmp)
    print("=" * 60)
    print("✅ تمام تست‌ها با موفقیت پاس شدند.")
    print("=" * 60)


# ══════════════════════════════════════════════════════════════════════════════
# به‌روزرسانی جوشکار — اضافه‌شده در فاز ۵ (خارج از CONTRACTS اصلی)
# ══════════════════════════════════════════════════════════════════════════════

def update_welder(
    welder_id: int,
    full_name: str,
    contractor_id: int,
    birth_date: str | None,
) -> None:
    """
    اطلاعات پایه جوشکار را به‌روز می‌کند.
    کد ملی قابل تغییر نیست (کلید یکتا).

    ورودی:
        welder_id:     شناسه جوشکار در جدول welders
        full_name:     نام کامل جدید
        contractor_id: شناسه پیمانکار جدید
        birth_date:    تاریخ تولد جدید یا None
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE welders
               SET full_name = ?, contractor_id = ?, birth_date = ?
             WHERE id = ?
            """,
            (full_name, contractor_id, birth_date, welder_id),
        )
        conn.commit()


def update_welder_photo(welder_id: int, photo_path: str) -> None:
    """
    مسیر عکس جوشکار را به‌روز می‌کند.

    ورودی:
        welder_id:  شناسه جوشکار
        photo_path: مسیر نسبی فایل عکس
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE welders SET photo_path = ? WHERE id = ?",
            (photo_path, welder_id),
        )
        conn.commit()
