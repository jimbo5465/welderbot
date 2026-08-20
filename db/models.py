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

def add_project(name: str) -> int:
    """
    پروژه جدید اضافه می‌کند (بدون پیمانکار — پیمانکارها بعداً با
    link_project_contractor به آن وصل می‌شوند).

    ورودی:
        name: نام پروژه (باید یکتا باشد)

    خروجی:
        id ردیف جدید در جدول projects

    خطا:
        sqlite3.IntegrityError اگر نام تکراری باشد
    """
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, is_active, created_at) VALUES (?, 1, ?)",
            (name, _now_str()),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def list_projects(active_only: bool = True) -> list[dict]:
    """
    فهرست پروژه‌ها را برمی‌گرداند (بدون فیلتر پیمانکار — هر پروژه می‌تواند
    چند پیمانکار داشته باشد؛ برای پیمانکارهای یک پروژه از
    list_contractors_by_project استفاده کنید).
    """
    with get_connection() as conn:
        query = "SELECT * FROM projects"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY name"
        rows = conn.execute(query).fetchall()
        return _rows_to_dicts(rows)


# ══════════════════════════════════════════════════════════════════════════════
# رابطه چند-به-چند پروژه ⇆ پیمانکار (جدول project_contractors) — فاز ۸
# ══════════════════════════════════════════════════════════════════════════════

def link_project_contractor(project_id: int, contractor_id: int) -> None:
    """یک پیمانکار را به یک پروژه وصل می‌کند. idempotent (تکرار بی‌خطر)."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO project_contractors (project_id, contractor_id) VALUES (?, ?)",
            (project_id, contractor_id),
        )
        conn.commit()


def unlink_project_contractor(project_id: int, contractor_id: int) -> None:
    """اتصال یک پیمانکار به یک پروژه را قطع می‌کند."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM project_contractors WHERE project_id = ? AND contractor_id = ?",
            (project_id, contractor_id),
        )
        conn.commit()


def list_contractors_by_project(project_id: int, active_only: bool = True) -> list[dict]:
    """
    فهرست پیمانکارهای متصل به یک پروژه مشخص را برمی‌گرداند.

    فاز ۱۰: active_only اکنون هم رابطهٔ پروژه⇆پیمانکار (project_contractors.status)
    و هم خود پیمانکار (contractors.is_active) را چک می‌کند — قبلاً فقط دومی را
    چک می‌کرد، که باعث می‌شد پیمانکار خاتمه‌یافته در یک پروژه هنوز قابل‌انتخاب باشد.
    """
    with get_connection() as conn:
        query = """
            SELECT c.* FROM contractors c
            JOIN project_contractors pc ON pc.contractor_id = c.id
            WHERE pc.project_id = ?
        """
        if active_only:
            query += " AND pc.status = 'active' AND c.is_active = 1"
        query += " ORDER BY c.name"
        rows = conn.execute(query, (project_id,)).fetchall()
        return _rows_to_dicts(rows)


def list_projects_by_contractor(contractor_id: int, active_only: bool = True) -> list[dict]:
    """فهرست پروژه‌هایی که یک پیمانکار مشخص در آن‌ها فعال است."""
    with get_connection() as conn:
        query = """
            SELECT p.* FROM projects p
            JOIN project_contractors pc ON pc.project_id = p.id
            WHERE pc.contractor_id = ?
        """
        if active_only:
            query += " AND p.is_active = 1"
        query += " ORDER BY p.name"
        rows = conn.execute(query, (contractor_id,)).fetchall()
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



# ══════════════════════════════════════════════════════════════════════════════
# مدیریت کاربران در انتظار (جدول pending_users) — فاز ۸
# ══════════════════════════════════════════════════════════════════════════════

def register_pending_user(telegram_id: int, full_name: str, username: str | None) -> None:
    """
    هر بار کاربر /start می‌زند فراخوانی می‌شود.
    اگر کاربر جدید است ثبت می‌شود؛ اگر قبلاً بوده، last_seen_at به‌روز می‌شود.
    idempotent است.
    """
    now = _now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pending_users (telegram_id, full_name, username, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                full_name = excluded.full_name,
                username = excluded.username,
                last_seen_at = excluded.last_seen_at
            """,
            (telegram_id, full_name, username, now, now),
        )
        conn.commit()


def list_pending_users(exclude_telegram_ids: list[int] | None = None) -> list[dict]:
    """فهرست کاربرانی که تا الان /start زده‌اند را برمی‌گرداند (جدیدترین اول)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM pending_users ORDER BY last_seen_at DESC"
        ).fetchall()
        result = _rows_to_dicts(rows)
        if exclude_telegram_ids:
            result = [r for r in result if r["telegram_id"] not in exclude_telegram_ids]
        return result


# ══════════════════════════════════════════════════════════════════════════════
# مدیریت سطوح دسترسی (جدول access_grants) — فاز ۸
# ══════════════════════════════════════════════════════════════════════════════

def add_access_grant(
    telegram_id: int,
    level: int,
    granted_by: int,
    project_id: int | None = None,
    contractor_id: int | None = None,
) -> int:
    """
    یک دسترسی جدید ثبت می‌کند.
    سطح ۱: project_id=None, contractor_id=None (سراسری)
    سطح ۲: project_id=مقدار, contractor_id=None
    سطح ۳: project_id=مقدار, contractor_id=مقدار
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO access_grants
                (telegram_id, level, project_id, contractor_id, granted_by, granted_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (telegram_id, level, project_id, contractor_id, granted_by, _now_str()),
        )
        conn.commit()
        return cur.lastrowid


def get_access_grants_by_telegram(telegram_id: int, active_only: bool = True) -> list[dict]:
    """تمام دسترسی‌های یک کاربر را برمی‌گرداند (ممکن است چند grant داشته باشد)."""
    with get_connection() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM access_grants WHERE telegram_id = ? AND is_active = 1",
                (telegram_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM access_grants WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchall()
        return _rows_to_dicts(rows)


def revoke_access_grant(grant_id: int) -> None:
    """یک دسترسی را غیرفعال می‌کند (soft-delete)."""
    with get_connection() as conn:
        conn.execute("UPDATE access_grants SET is_active = 0 WHERE id = ?", (grant_id,))
        conn.commit()


def list_grants_by_project(project_id: int) -> list[dict]:
    """تمام دسترسی‌های سطح ۲ و ۳ مربوط به یک پروژه را برمی‌گرداند."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM access_grants WHERE project_id = ? AND is_active = 1",
            (project_id,),
        ).fetchall()
        return _rows_to_dicts(rows)
# ══════════════════════════════════════════════════════════════════════════════
# این بلوک را به انتهای db/models.py اضافه کنید.
# چرخهٔ حیات پروژه — فاز ۹ (خاتمه/فعال‌سازی مجدد پروژه)
#
# قوانین قفل‌شده (طبق تصمیمات فاز ۹):
#   - خاتمهٔ پروژه = soft (is_active=0)، قابل بازگشت، فقط سطح ۱ (گیت در handler)
#   - نام پروژه حتی بعد از خاتمه یکتا می‌ماند (UNIQUE constraint فعلی جدول کافی است)
#   - خاتمه هیچ رکورد وابسته‌ای (پیمانکار/جوشکار/صلاحیت) را تغییر نمی‌دهد
# ══════════════════════════════════════════════════════════════════════════════

def get_project_by_id(project_id: int) -> dict | None:
    """
    پروژه را با شناسه برمی‌گرداند.

    ورودی:
        project_id: شناسه پروژه

    خروجی:
        dict شامل تمام فیلدهای جدول projects، یا None اگر یافت نشد
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        return _row_to_dict(row)


def update_project_name(project_id: int, name: str) -> None:
    """
    نام پروژه را تغییر می‌دهد (تنها فیلد قابل‌ویرایش پروژه در حال حاضر).

    ورودی:
        project_id: شناسه پروژه
        name:       نام جدید (باید یکتا باشد)

    خطا:
        sqlite3.IntegrityError اگر نام تکراری باشد (حتی با پروژهٔ غیرفعال)
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE projects SET name = ? WHERE id = ?",
            (name, project_id),
        )
        conn.commit()


def set_project_inactive(project_id: int) -> None:
    """
    پروژه را خاتمه می‌دهد (soft-delete: is_active = 0).
    هرگز DELETE — رکوردهای وابسته (project_contractors، qualifications با
    این project_id) دست‌نخورده و قابل مشاهده باقی می‌مانند.

    ورودی:
        project_id: شناسه پروژه
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE projects SET is_active = 0 WHERE id = ?",
            (project_id,),
        )
        conn.commit()


def reactivate_project(project_id: int) -> None:
    """
    پروژهٔ خاتمه‌یافته را دوباره فعال می‌کند (is_active = 1).

    ورودی:
        project_id: شناسه پروژه
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE projects SET is_active = 1 WHERE id = ?",
            (project_id,),
        )
        conn.commit()


def get_project_stats(project_id: int) -> dict:
    """
    شمار رکوردهای فعال وابسته به یک پروژه را برمی‌گرداند — برای نمایش
    هشدار به سطح ۱ قبل از خاتمهٔ پروژه («این پروژه شامل X پیمانکار فعال
    و Y صلاحیت فعال است»).

    ورودی:
        project_id: شناسه پروژه

    خروجی:
        dict:
            active_contractors:    تعداد پیمانکار فعال متصل به این پروژه
            active_qualifications: تعداد صلاحیت فعال ثبت‌شده در این پروژه
    """
    with get_connection() as conn:
        contractors_count = conn.execute(
            """
            SELECT COUNT(*) FROM project_contractors pc
            JOIN contractors c ON c.id = pc.contractor_id
            WHERE pc.project_id = ? AND c.is_active = 1
            """,
            (project_id,),
        ).fetchone()[0]

        qualifications_count = conn.execute(
            "SELECT COUNT(*) FROM qualifications WHERE project_id = ? AND is_active = 1",
            (project_id,),
        ).fetchone()[0]

        return {
            "active_contractors": contractors_count,
            "active_qualifications": qualifications_count,
        }


# ══════════════════════════════════════════════════════════════════════════════
# این بلوک را به انتهای db/models.py اضافه کنید.
# پیش‌نیاز: migration فاز ۹.۵ (db_init_migration_ADD_TO_init_py.py) باید قبلاً
# روی دیتابیس اجرا شده باشد (project_contractors ستون‌های id/status/label دارد).
#
# مدل ذهنی:
#   - contractors: entity سراسری، فقط name/is_active/created_at. name یکتاست.
#   - project_contractors: رابطهٔ پروژه⇆پیمانکار با چرخهٔ‌حیات مستقل از خود
#     پیمانکار. یک جفت (project_id, contractor_id) می‌تواند چند رکورد
#     تاریخی داشته باشد اما فقط یکی status='active'.
#   - "خاتمهٔ پیمانکار در پروژه" یعنی خاتمهٔ همین رکورد رابطه، نه خود پیمانکار.
# ══════════════════════════════════════════════════════════════════════════════



def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── پیمانکار (entity سراسری) ────────────────────────────────────────────────

def get_contractor_by_id(contractor_id: int) -> dict | None:
    """پیمانکار را با شناسه برمی‌گرداند، یا None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM contractors WHERE id = ?", (contractor_id,)
        ).fetchone()
        return _row_to_dict(row)


def get_contractor_by_name(name: str) -> dict | None:
    """
    پیمانکار را با نام دقیق (case-sensitive) برمی‌گرداند.
    برای تشخیص «این پیمانکار قبلاً در پروژهٔ دیگری ثبت شده، لینک کنیم نه
    دوباره بسازیم» استفاده می‌شود.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM contractors WHERE name = ?", (name,)
        ).fetchone()
        return _row_to_dict(row)


def update_contractor_name(contractor_id: int, name: str) -> None:
    """
    نام سراسری پیمانکار را تغییر می‌دهد. این تغییر روی همهٔ پروژه‌هایی که
    این پیمانکار در آن‌ها لینک شده اثر می‌گذارد — فقط سطح ۱ باید این را
    صدا بزند (گیت در handler، نه اینجا).

    خطا:
        sqlite3.IntegrityError اگر نام تکراری باشد
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE contractors SET name = ? WHERE id = ?",
            (name, contractor_id),
        )
        conn.commit()


# ── رابطهٔ پروژه⇆پیمانکار (چرخهٔ حیات) ──────────────────────────────────────

def link_contractor_to_project(
    project_id: int,
    contractor_id: int,
    linked_by: int,
    label: str | None = None,
) -> int:
    """
    پیمانکار را به پروژه لینک می‌کند (وضعیت اولیه: active).
    هم برای اولین لینک و هم برای «الحاق مجدد» بعد از خاتمه استفاده می‌شود —
    چون partial unique index فقط مانع دو لینک *فعال* هم‌زمان می‌شود، نه
    مانع رکورد جدید بعد از یک رکورد terminated قدیمی.

    ورودی:
        linked_by: telegram_id کاربری که لینک را ایجاد کرد
        label:     برچسب اختیاری («الحاقیه»، «فاز ۲» ...)

    خروجی:
        id رکورد لینک تازه‌ساخته‌شده

    خطا:
        sqlite3.IntegrityError اگر این جفت از قبل لینک *فعال* داشته باشد
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO project_contractors
                (project_id, contractor_id, label, status, linked_by, linked_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (project_id, contractor_id, label, linked_by, _now_iso()),
        )
        conn.commit()
        return cur.lastrowid


def get_link_by_id(link_id: int) -> dict | None:
    """
    رکورد رابطهٔ پروژه⇆پیمانکار را به‌همراه نام پیمانکار و نام پروژه برمی‌گرداند.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT pc.*, c.name AS contractor_name, p.name AS project_name
            FROM project_contractors pc
            JOIN contractors c ON c.id = pc.contractor_id
            JOIN projects p ON p.id = pc.project_id
            WHERE pc.id = ?
            """,
            (link_id,),
        ).fetchone()
        return _row_to_dict(row)


def list_contractor_links_by_project(
    project_id: int, statuses: tuple[str, ...] | None = None
) -> list[dict]:
    """
    فهرست رابطه‌های پیمانکار برای یک پروژه — به‌همراه نام پیمانکار.

    ورودی:
        statuses: اگر داده شود فقط این وضعیت‌ها (مثلاً ('active',))، وگرنه همه
    """
    with get_connection() as conn:
        if statuses:
            placeholders = ",".join("?" * len(statuses))
            rows = conn.execute(
                f"""
                SELECT pc.*, c.name AS contractor_name
                FROM project_contractors pc
                JOIN contractors c ON c.id = pc.contractor_id
                WHERE pc.project_id = ? AND pc.status IN ({placeholders})
                ORDER BY c.name
                """,
                (project_id, *statuses),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT pc.*, c.name AS contractor_name
                FROM project_contractors pc
                JOIN contractors c ON c.id = pc.contractor_id
                WHERE pc.project_id = ?
                ORDER BY c.name
                """,
                (project_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def update_link_label(link_id: int, label: str | None) -> None:
    """برچسب یک رابطهٔ پروژه⇆پیمانکار را تغییر می‌دهد (نه نام خود پیمانکار)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE project_contractors SET label = ? WHERE id = ?",
            (label, link_id),
        )
        conn.commit()


def terminate_link_direct(link_id: int, terminated_by: int) -> None:
    """
    خاتمهٔ مستقیم رابطه — فقط سطح ۱. بدون فلوی درخواست/تأیید.
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE project_contractors
            SET status = 'terminated', terminated_by = ?, terminated_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (terminated_by, _now_iso(), link_id),
        )
        conn.commit()


def request_terminate_link(link_id: int, requested_by: int) -> None:
    """
    درخواست خاتمهٔ رابطه توسط سطح ۲ — نیاز به تأیید سطح ۱.
    status: active -> pending_termination
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE project_contractors
            SET status = 'pending_termination',
                termination_requested_by = ?, termination_requested_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (requested_by, _now_iso(), link_id),
        )
        conn.commit()


def approve_terminate_link(link_id: int, approved_by: int) -> None:
    """تأیید سطح ۱ روی یک درخواست خاتمه. status: pending_termination -> terminated"""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE project_contractors
            SET status = 'terminated', terminated_by = ?, terminated_at = ?
            WHERE id = ? AND status = 'pending_termination'
            """,
            (approved_by, _now_iso(), link_id),
        )
        conn.commit()


def reject_terminate_link(link_id: int, reason: str) -> None:
    """
    رد درخواست خاتمه توسط سطح ۱ — رابطه به حالت active برمی‌گردد.
    دلیل رد ذخیره می‌شود تا به سطح ۲ نمایش داده شود.
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE project_contractors
            SET status = 'active', reject_reason = ?,
                termination_requested_by = NULL, termination_requested_at = NULL
            WHERE id = ? AND status = 'pending_termination'
            """,
            (reason, link_id),
        )
        conn.commit()


def list_pending_termination_requests() -> list[dict]:
    """
    همهٔ درخواست‌های خاتمهٔ در انتظار تأیید (سراسری، برای صف سطح ۱).
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT pc.*, c.name AS contractor_name, p.name AS project_name
            FROM project_contractors pc
            JOIN contractors c ON c.id = pc.contractor_id
            JOIN projects p ON p.id = pc.project_id
            WHERE pc.status = 'pending_termination'
            ORDER BY pc.termination_requested_at
            """
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def is_link_active(project_id: int, contractor_id: int) -> bool:
    """
    آیا این جفت پروژه/پیمانکار در حال حاضر لینک فعال دارند؟
    برای گیت کردن «ثبت فعالیت جدید» در ماژول‌های دیگر (جوش، آینده: رنگ/فیتینگ)
    در نظر گرفته شده — در همین فاز جایی صدا زده نمی‌شود.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM project_contractors
            WHERE project_id = ? AND contractor_id = ? AND status = 'active'
            """,
            (project_id, contractor_id),
        ).fetchone()
        return row is not None


# ══════════════════════════════════════════════════════════════════════════════
# گزارش عدم انطباق (NCR) — فاز NCR
# ══════════════════════════════════════════════════════════════════════════════
# چرخهٔ حیات: draft (پیش‌نویس) → submitted (ثبت نهایی + شماره‌دهی + خروجی اکسل)
# هر NCR به یک (project_id, contractor_id) متصل است. عکس‌ها در جدول ncr_photos.
# فیلدهای انعطاف‌پذیر آینده در extra_data (JSON) ذخیره می‌شوند.


def _deserialize_ncr(row: sqlite3.Row | None) -> dict | None:
    """ردیف ncrs را به dict تبدیل می‌کند؛ extra_data را از JSON به dict می‌سازد."""
    if row is None:
        return None
    d = dict(row)
    if isinstance(d.get("extra_data"), str):
        try:
            d["extra_data"] = json.loads(d["extra_data"])
        except (json.JSONDecodeError, TypeError):
            d["extra_data"] = {}
    elif d.get("extra_data") is None:
        d["extra_data"] = {}
    return d


def add_ncr(
    project_id: int,
    contractor_id: int,
    reported_by: int,
    reporter_name: str,
    reporter_title: str | None = None,
    island: str | None = None,
    unit: str | None = None,
    operation_type: str | None = None,
    discipline: str | None = None,
    drawing_number: str | None = None,
    description: str | None = None,
    cause: str | None = None,
    corrective_action: str | None = None,
    hse_confirmed: int | None = None,
    equipment_description: str | None = None,
    reported_date: str | None = None,
    extra_data: dict | None = None,
) -> int:
    """
    یک گزارش NCR جدید ثبت می‌کند (وضعیت اولیه: draft).

    ورودی:
        project_id:    پروژه‌ای که عدم انطباق در آن رخ داده است
        contractor_id: پیمانکار مسئول
        reported_by:   telegram_id گزارش‌دهنده (کاربر ثبت‌شده)
        reporter_name: نام گزارش‌دهنده (پرسیده می‌شود)
        reporter_title: سمت گزارش‌دهنده (اختیاری)

    خروجی:
        id ردیف جدید در جدول ncrs
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO ncrs (
                project_id, contractor_id, status, island, unit,
                operation_type, discipline, drawing_number, description, cause,
                corrective_action, hse_confirmed, equipment_description,
                reporter_name, reporter_title, reported_by, reported_date,
                is_active, created_at, extra_data
            ) VALUES (
                ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?
            )
            """,
            (
                project_id, contractor_id, island, unit,
                operation_type, discipline, drawing_number, description, cause,
                corrective_action, hse_confirmed, equipment_description,
                reporter_name, reporter_title, reported_by, reported_date,
                _now_str(),
                json.dumps(extra_data, ensure_ascii=False) if extra_data else None,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def get_ncr_by_id(ncr_id: int) -> dict | None:
    """
    یک گزارش NCR را با شناسه برمی‌گرداند (به‌همراه نام پروژه/پیمانکار).
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT n.*, p.name AS project_name, c.name AS contractor_name
            FROM ncrs n
            JOIN projects p ON p.id = n.project_id
            JOIN contractors c ON c.id = n.contractor_id
            WHERE n.id = ?
            """,
            (ncr_id,),
        ).fetchone()
        return _deserialize_ncr(row)


def update_ncr(ncr_id: int, fields: dict) -> None:
    """
    فیلدهای مشخص‌شده یک NCR را به‌روزرسانی می‌کند (فعلاً برای draft).

    ورودی:
        ncr_id: شناسه NCR
        fields: dict از ستون → مقدار (فقط ستون‌های مجاز زیر)

    نکته: این تابع فقط فیلدهای تکست/عدد ساده را می‌گیرد. اگر فیلد ncr_number
          یا submitted_at باید تغییر کند، از submit_ncr استفاده کنید.
    """
    allowed = {
        "project_id", "contractor_id", "island", "unit", "operation_type",
        "discipline", "drawing_number", "description", "cause",
        "corrective_action", "hse_confirmed", "equipment_description",
        "reporter_name", "reporter_title", "reported_date",
    }
    to_set = {k: v for k, v in fields.items() if k in allowed}
    if not to_set:
        return
    assignments = ", ".join(f"{k} = ?" for k in to_set)
    values = list(to_set.values()) + [ncr_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE ncrs SET {assignments} WHERE id = ?", values)
        conn.commit()


def set_ncr_extra(ncr_id: int, extra_data: dict) -> None:
    """extra_data یک NCR را به‌روزرسانی می‌کند (JSON)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE ncrs SET extra_data = ? WHERE id = ?",
            (json.dumps(extra_data, ensure_ascii=False), ncr_id),
        )
        conn.commit()


def submit_ncr(ncr_id: int, ncr_number: str, excel_path: str) -> None:
    """
    یک NCR را به‌صورت نهایی ثبت می‌کند:
      - وضعیت را به submitted تغییر می‌دهد
      - شماره NCR اختصاص می‌دهد
      - مسیر فایل Excel خروجی را ذخیره می‌کند
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE ncrs
            SET status = 'submitted', ncr_number = ?, excel_path = ?, submitted_at = ?
            WHERE id = ?
            """,
            (ncr_number, excel_path, _now_str(), ncr_id),
        )
        conn.commit()


def reopen_ncr(ncr_id: int) -> None:
    """
    یک NCR ثبت‌شده را به وضعیت draft برمی‌گرداند (برای ویرایش مجدد).
    شماره و مسیر خروجی پاک می‌شوند تا بعد از ثبت دوباره ساخته شوند.
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE ncrs
            SET status = 'draft', ncr_number = NULL, excel_path = NULL, submitted_at = NULL
            WHERE id = ?
            """,
            (ncr_id,),
        )
        conn.commit()


def set_ncr_inactive(ncr_id: int) -> None:
    """NCR را غیرفعال می‌کند (soft-delete)."""
    with get_connection() as conn:
        conn.execute("UPDATE ncrs SET is_active = 0 WHERE id = ?", (ncr_id,))
        conn.commit()


def list_ncrs_by_project(
    project_id: int,
    statuses: tuple[str, ...] | None = None,
    active_only: bool = True,
) -> list[dict]:
    """
    فهرست گزارش‌های NCR یک پروژه (جدیدترین اول).

    ورودی:
        statuses: اگر داده شود فقط این وضعیت‌ها (مثلاً ('draft',))
    """
    with get_connection() as conn:
        query = "SELECT * FROM ncrs WHERE project_id = ?"
        params: list = [project_id]
        if active_only:
            query += " AND is_active = 1"
        if statuses:
            placeholders = ",".join("?" * len(statuses))
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [_deserialize_ncr(r) for r in rows]  # type: ignore[misc]


def list_ncrs_by_contractor(contractor_id: int, active_only: bool = True) -> list[dict]:
    """فهرست گزارش‌های NCR یک پیمانکار (جدیدترین اول)."""
    with get_connection() as conn:
        query = "SELECT * FROM ncrs WHERE contractor_id = ?"
        params: list = [contractor_id]
        if active_only:
            query += " AND is_active = 1"
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [_deserialize_ncr(r) for r in rows]  # type: ignore[misc]


def list_all_ncrs(active_only: bool = True) -> list[dict]:
    """فهرست تمام گزارش‌های NCR (جدیدترین اول)."""
    with get_connection() as conn:
        query = "SELECT * FROM ncrs"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query).fetchall()
        return [_deserialize_ncr(r) for r in rows]  # type: ignore[misc]


# ── عکس‌های NCR ────────────────────────────────────────────────────────────────

def add_ncr_photo(ncr_id: int, path: str) -> int:
    """مسیر یک عکس را به NCR اضافه می‌کند."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO ncr_photos (ncr_id, path, uploaded_at) VALUES (?, ?, ?)",
            (ncr_id, path, _now_str()),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def list_ncr_photos(ncr_id: int) -> list[dict]:
    """فهرست عکس‌های یک NCR (به ترتیب آپلود)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ncr_photos WHERE ncr_id = ? ORDER BY id",
            (ncr_id,),
        ).fetchall()
        return _rows_to_dicts(rows)


# ══════════════════════════════════════════════════════════════════════════════
# ثبت دانش/تجربه (فاز دانش سازمانی — جدول knowledge_entries)
# ══════════════════════════════════════════════════════════════════════════════
# چرخهٔ حیات: draft (پیش‌نویس) → submitted (ثبت نهایی + شماره‌دهی)
# هر رکورد به یک (project_id, contractor_id) متصل است. عکس‌ها در knowledge_photos.
# فیلدهای ساختاریافته در fields_json (JSON) — استخراج AI + تکمیل دستی کاربر.


def _deserialize_knowledge(row: sqlite3.Row | None) -> dict | None:
    """ردیف knowledge_entries را به dict تبدیل می‌کند؛ JSONها را از هم باز می‌کند."""
    if row is None:
        return None
    d = dict(row)
    if isinstance(d.get("fields_json"), str):
        try:
            d["fields_json"] = json.loads(d["fields_json"])
        except (json.JSONDecodeError, TypeError):
            d["fields_json"] = {}
    if isinstance(d.get("extra_data"), str):
        try:
            d["extra_data"] = json.loads(d["extra_data"])
        except (json.JSONDecodeError, TypeError):
            d["extra_data"] = {}
    elif d.get("extra_data") is None:
        d["extra_data"] = {}
    return d


def add_knowledge_entry(
    project_id: int | None,
    contractor_id: int | None,
    reported_by: int,
    knowledge_type: str,
    reporter_name: str,
    reporter_title: str | None = None,
    raw_description: str | None = None,
    fields: dict | None = None,
    draft_text: str | None = None,
    reported_date: str | None = None,
    extra_data: dict | None = None,
) -> int:
    """
    یک رکورد دانش/تجربه جدید ثبت می‌کند (وضعیت اولیه: draft).

    ورودی:
        project_id:     پروژهٔ محل وقوع تجربه — از فاز۳ اختیاری است
                        (تجربه لزوماً به پروژهٔ خاصی وابسته نیست؛ اگر در متن
                        بیاید در polish استخراج میشود). None = NULL در DB.
        contractor_id:  پیمانکار مرتبط — اختیاری (همانند project_id)
        reported_by:    شناسهٔ کاربر گزارش‌دهنده در جدول users
        knowledge_type: 'lesson' | 'suggestion' | 'explicit'
        fields:         فیلدهای ساختاریافته (dict) — به JSON تبدیل می‌شود
        draft_text:     پیش‌نویس متنی DANA تولیدشده

    خروجی:
        id ردیف جدید در جدول knowledge_entries
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO knowledge_entries (
                project_id, contractor_id, status, knowledge_type,
                reporter_name, reporter_title, reported_by,
                raw_description, fields_json, draft_text,
                reported_date, is_active, created_at, extra_data
            ) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                project_id, contractor_id, knowledge_type,
                reporter_name, reporter_title, reported_by,
                raw_description,
                json.dumps(fields, ensure_ascii=False) if fields else None,
                draft_text,
                reported_date,
                _now_str(),
                json.dumps(extra_data, ensure_ascii=False) if extra_data else None,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def get_knowledge_entry_by_id(knowledge_id: int) -> dict | None:
    """یک رکورد دانش را با شناسه برمیگرداند (به‌همراه نام پروژه/پیمانکار)."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT k.*, p.name AS project_name, c.name AS contractor_name
            FROM knowledge_entries k
            LEFT JOIN projects p ON p.id = k.project_id
            LEFT JOIN contractors c ON c.id = k.contractor_id
            WHERE k.id = ?
            """,
            (knowledge_id,),
        ).fetchone()
        return _deserialize_knowledge(row)


def set_knowledge_fields(knowledge_id: int, fields: dict, draft_text: str | None = None) -> None:
    """فیلدهای ساختاریافته (و متن پیش‌نویس اختیاری) یک رکورد دانش را به‌روز می‌کند."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE knowledge_entries SET fields_json = ?, draft_text = ? WHERE id = ?",
            (json.dumps(fields, ensure_ascii=False), draft_text, knowledge_id),
        )
        conn.commit()


def submit_knowledge_entry(
    knowledge_id: int,
    kn_number: str,
    pdf_path: str | None = None,
    docx_path: str | None = None,
) -> None:
    """
    ثبت نهایی: وضعیت → submitted + اختصاص شماره + زمان ثبت.
    مسیرهای خروجی PDF/DOCX (اختیاری) هم ذخیره می‌شوند.
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE knowledge_entries
            SET status = 'submitted', kn_number = ?, submitted_at = ?,
                pdf_path = ?, docx_path = ?
            WHERE id = ?
            """,
            (kn_number, _now_str(), pdf_path, docx_path, knowledge_id),
        )
        conn.commit()


def set_knowledge_inactive(knowledge_id: int) -> None:
    """رکورد دانش را غیرفعال می‌کند (soft-delete)."""
    with get_connection() as conn:
        conn.execute("UPDATE knowledge_entries SET is_active = 0 WHERE id = ?", (knowledge_id,))
        conn.commit()


def list_knowledge_entries(active_only: bool = True) -> list[dict]:
    """فهرست تمام رکوردهای دانش (جدیدترین اول)."""
    with get_connection() as conn:
        query = "SELECT * FROM knowledge_entries"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query).fetchall()
        return [_deserialize_knowledge(r) for r in rows]  # type: ignore[misc]


def list_knowledge_entries_by_project(
    project_id: int,
    statuses: tuple[str, ...] | None = None,
    active_only: bool = True,
) -> list[dict]:
    """فهرست رکوردهای دانش یک پروژه (جدیدترین اول)."""
    with get_connection() as conn:
        query = "SELECT * FROM knowledge_entries WHERE project_id = ?"
        params: list = [project_id]
        if active_only:
            query += " AND is_active = 1"
        if statuses:
            placeholders = ",".join("?" * len(statuses))
            query += f" AND status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [_deserialize_knowledge(r) for r in rows]  # type: ignore[misc]


# ── عکس‌های دانش ─────────────────────────────────────────────────────────────

def add_knowledge_photo(knowledge_id: int, path: str) -> int:
    """مسیر یک عکس را به رکورد دانش اضافه می‌کند."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO knowledge_photos (knowledge_id, path, uploaded_at) VALUES (?, ?, ?)",
            (knowledge_id, path, _now_str()),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def list_knowledge_photos(knowledge_id: int) -> list[dict]:
    """فهرست عکس‌های یک رکورد دانش (به ترتیب آپلود)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM knowledge_photos WHERE knowledge_id = ? ORDER BY id",
            (knowledge_id,),
        ).fetchall()
        return _rows_to_dicts(rows)


# ══════════════════════════════════════════════════════════════════════════════
# توابع فاز۳ — مصاحبه / درخت دانش / متادیتای سازمانی / resume
# ══════════════════════════════════════════════════════════════════════════════


def set_knowledge_interview_history(knowledge_id: int, history: list) -> None:
    """
    تاریخچهٔ مکالمهٔ مصاحا را در DB ذخیره میکند.
    history: لیست پیامها به شکل [{role: 'user'|'assistant', content: str}, ...]
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE knowledge_entries SET interview_history_json = ? WHERE id = ?",
            (json.dumps(history, ensure_ascii=False) if history else None,
             knowledge_id),
        )
        conn.commit()


def get_knowledge_interview_history(knowledge_id: int) -> list:
    """تاریخچهٔ مصاحبه را از DB میخواند (لیست خالی اگر وجود نداشته باشد)."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT interview_history_json FROM knowledge_entries WHERE id = ?",
            (knowledge_id,),
        ).fetchone()
    raw = row["interview_history_json"] if row else None
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def set_knowledge_tree_path(knowledge_id: int, path: list[str]) -> None:
    """مسیر انتخابی درخت دانش را ذخیره میکند (آرایه از نام نودها)."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE knowledge_entries SET tree_path_json = ? WHERE id = ?",
            (json.dumps(path, ensure_ascii=False) if path else None,
             knowledge_id),
        )
        conn.commit()


def get_knowledge_tree_path(knowledge_id: int) -> list[str]:
    """مسیر درخت دانش ذخیره‌شده را برمیگرداند."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT tree_path_json FROM knowledge_entries WHERE id = ?",
            (knowledge_id,),
        ).fetchone()
    raw = row["tree_path_json"] if row else None
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def set_knowledge_org_metadata(knowledge_id: int, org_data: dict) -> None:
    """
    متادیتای سازمانی را ذخیره میکند.
    org_data کلیدهای ممکن: committee, seed, colleagues, scope, hashtags_override.
    """
    with get_connection() as conn:
        conn.execute(
            "UPDATE knowledge_entries SET org_metadata_json = ? WHERE id = ?",
            (json.dumps(org_data, ensure_ascii=False) if org_data else None,
             knowledge_id),
        )
        conn.commit()


def get_knowledge_org_metadata(knowledge_id: int) -> dict:
    """متادیتای سازمانی ذخیره‌شده را برمیگرداند."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT org_metadata_json FROM knowledge_entries WHERE id = ?",
            (knowledge_id,),
        ).fetchone()
    raw = row["org_metadata_json"] if row else None
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def find_pending_knowledge_by_user(telegram_id: int) -> dict | None:
    """
    آخرین رکورد دانش ناتمام (draft بدون kn_number) یک کاربر را برمیگرداند —
    برای قابلیت resume بعد از restart ربات استفاده میشود.

    ناتمام = status='draft' AND kn_number IS NULL AND (interview_history_json
    یا raw_description پر باشد — یعنی ثبت شروع شده ولی تمام نشده).
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT k.*
            FROM knowledge_entries k
            JOIN users u ON u.id = k.reported_by
            WHERE u.telegram_id = ?
              AND k.status = 'draft'
              AND k.kn_number IS NULL
              AND (k.interview_history_json IS NOT NULL
                   OR (k.raw_description IS NOT NULL AND k.raw_description != ''))
            ORDER BY k.created_at DESC
            LIMIT 1
            """,
            (telegram_id,),
        ).fetchone()
        return _deserialize_knowledge(row)
