"""
ماژول init — ساخت جداول پایگاه داده و مقداردهی اولیه.
CREATE TABLE statements دقیقاً از DATA_SCHEMA.md کپی شده‌اند.
این ماژول فقط از config import می‌کند.
"""

from __future__ import annotations

import sqlite3
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """
    اتصال به پایگاه داده SQLite را با تنظیمات استاندارد برمی‌گرداند.

    ویژگی‌ها:
        - row_factory = sqlite3.Row (دسترسی به ستون‌ها با نام)
        - PRAGMA foreign_keys = ON (اعمال محدودیت‌های کلید خارجی)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """
    پایگاه داده SQLite را مقداردهی اولیه می‌کند.

    عملکرد:
        - تمام جداول را با CREATE TABLE IF NOT EXISTS می‌سازد.
        - شاخص‌های لازم را ایجاد می‌کند.
        - seed data اولیه (P-Numberها و F-Numberها) را وارد می‌کند.
        - idempotent است — اجرای مکرر بی‌خطر است.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()

        # ── جدول users ──────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id     INTEGER NOT NULL UNIQUE,
                full_name       TEXT    NOT NULL,
                role            TEXT    NOT NULL
                                CHECK (role IN ('admin', 'operator')),
                is_active       INTEGER NOT NULL DEFAULT 1
                                CHECK (is_active IN (0, 1)),
                created_at      TEXT    NOT NULL
            )
        """)

        # ── جدول contractors ─────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contractors (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT    NOT NULL UNIQUE,
                is_active       INTEGER NOT NULL DEFAULT 1
                                CHECK (is_active IN (0, 1)),
                created_at      TEXT    NOT NULL
            )
        """)

        # ── جدول projects ────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT    NOT NULL,
                contractor_id   INTEGER NOT NULL
                                REFERENCES contractors(id),
                is_active       INTEGER NOT NULL DEFAULT 1
                                CHECK (is_active IN (0, 1)),
                created_at      TEXT    NOT NULL,
                UNIQUE (name, contractor_id)
            )
        """)

        # ── جدول materials ───────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS materials (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                p_number        TEXT    NOT NULL UNIQUE,
                description     TEXT,
                is_active       INTEGER NOT NULL DEFAULT 1
                                CHECK (is_active IN (0, 1))
            )
        """)

        # ── جدول fillers ─────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fillers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                f_number        TEXT    NOT NULL UNIQUE,
                aws_class       TEXT,
                description     TEXT,
                is_active       INTEGER NOT NULL DEFAULT 1
                                CHECK (is_active IN (0, 1))
            )
        """)

        # ── جدول welders ─────────────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS welders (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                national_id     TEXT    NOT NULL UNIQUE,
                full_name       TEXT    NOT NULL,
                contractor_id   INTEGER NOT NULL
                                REFERENCES contractors(id),
                photo_path      TEXT,
                birth_date      TEXT,
                is_active       INTEGER NOT NULL DEFAULT 1
                                CHECK (is_active IN (0, 1)),
                created_at      TEXT    NOT NULL
            )
        """)

        # ── جدول qualifications ──────────────────────────────────────────────
        # این جدول شامل ۸ ستون qr_* قفل‌شده از DATA_SCHEMA.md است
        cur.execute("""
            CREATE TABLE IF NOT EXISTS qualifications (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,

                welder_id               INTEGER NOT NULL REFERENCES welders(id),
                project_id              INTEGER NOT NULL REFERENCES projects(id),
                recorded_by             INTEGER NOT NULL REFERENCES users(id),

                process                 TEXT    NOT NULL,
                backing                 TEXT    NOT NULL
                                        CHECK (backing IN ('با backing', 'بدون backing')),
                base_metal_p_no         TEXT    NOT NULL,
                filler_f_no             TEXT    NOT NULL,
                filler_aws_class        TEXT,
                deposit_groove_mm       REAL,
                deposit_fillet_mm       REAL,
                pass_count              INTEGER NOT NULL DEFAULT 1
                                        CHECK (pass_count >= 1),
                specimen_type           TEXT    NOT NULL
                                        CHECK (specimen_type IN ('PIPE', 'PLATE')),
                pipe_od_mm              REAL,
                test_position           TEXT    NOT NULL,
                joint_type              TEXT    NOT NULL
                                        CHECK (joint_type IN ('GROOVE', 'FILLET', 'GROOVE+FILLET')),
                test_date               TEXT    NOT NULL,

                qr_process              TEXT    NOT NULL,
                qr_backing              TEXT    NOT NULL,
                qr_p_no                 TEXT    NOT NULL,
                qr_thickness            TEXT    NOT NULL,
                qr_diameter             TEXT    NOT NULL,
                qr_position_groove      TEXT    NOT NULL,
                qr_position_fillet      TEXT    NOT NULL,
                qr_f_no                 TEXT    NOT NULL,

                expiry_date             TEXT    NOT NULL,
                signer_name             TEXT,
                signer_title            TEXT,

                is_active               INTEGER NOT NULL DEFAULT 1
                                        CHECK (is_active IN (0, 1)),
                created_at              TEXT    NOT NULL,

                -- فیلدهای انعطاف‌پذیر: هر داده اضافی به صورت JSON اینجا ذخیره می‌شود
                -- با این روش هرگز نیازی به تغییر schema نیست
                extra_data              TEXT
            )
        """)

        # ── migration: اضافه کردن extra_data به جدول قدیمی در صورت نبود ──────
        try:
            cur.execute("ALTER TABLE qualifications ADD COLUMN extra_data TEXT")
        except Exception:
            pass  # ستون قبلاً وجود دارد

        # ── شاخص‌ها (از DATA_SCHEMA.md) ──────────────────────────────────────
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_welders_national_id
            ON welders(national_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_welders_contractor
            ON welders(contractor_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_qualifications_welder
            ON qualifications(welder_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_qualifications_expiry
            ON qualifications(expiry_date)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_qualifications_project
            ON qualifications(project_id)
        """)

        # ── seed data: P-Numberها (QW-423.1) ─────────────────────────────────
        _seed_materials(cur)

        # ── seed data: F-Numberها (QW-433) ───────────────────────────────────
        _seed_fillers(cur)

        conn.commit()
    finally:
        conn.close()


def _seed_materials(cur: sqlite3.Cursor) -> None:
    """P-Numberهای استاندارد ASME را در جدول materials وارد می‌کند (اگر نباشند)."""
    materials = [
        ("P1",   "فولاد کربنی (Carbon Steel)"),
        ("P3",   "فولاد کم‌آلیاژ (Low Alloy Steel)"),
        ("P4",   "فولاد کروم-مولیبدن (Cr-Mo Steel)"),
        ("P5A",  "فولاد کروم-مولیبدن ۵٪ (5Cr-Mo Steel)"),
        ("P5B",  "فولاد کروم-مولیبدن ۹٪ (9Cr-Mo Steel)"),
        ("P8",   "فولاد ضدزنگ آوستنیتی (Austenitic Stainless Steel)"),
        ("P9A",  "فولاد نیکل ۲.۵٪ (2.5Ni Steel)"),
        ("P9B",  "فولاد نیکل ۳.۵٪ (3.5Ni Steel)"),
        ("P15E", "فولاد کم‌کربن کروم بالا (High-Cr Low-C Steel)"),
        ("P15F", "فولاد کروم-مولیبدن-ونادیوم (Cr-Mo-V Steel)"),
        ("P34",  "فولاد دوفازی (Duplex Stainless Steel)"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO materials (p_number, description) VALUES (?, ?)",
        materials,
    )


def _seed_fillers(cur: sqlite3.Cursor) -> None:
    """F-Numberهای استاندارد ASME را در جدول fillers وارد می‌کند (اگر نباشند)."""
    fillers = [
        ("F1", None, "الکترودهای فولادی پوشش‌دار گروه ۱"),
        ("F2", None, "الکترودهای فولادی پوشش‌دار گروه ۲"),
        ("F3", None, "الکترودهای فولادی پوشش‌دار گروه ۳"),
        ("F4", None, "الکترودهای فولادی پوشش‌دار گروه ۴"),
        ("F5", None, "الکترودهای فولاد ضدزنگ"),
        ("F6", None, "سیم‌جوش‌های فلزی رشته‌ای (Rod/Wire)"),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO fillers (f_number, aws_class, description) VALUES (?, ?, ?)",
        fillers,
    )


# ── تست سریع ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile, os
    # برای تست از یک دیتابیس موقت استفاده می‌کنیم
    tmp = tempfile.mktemp(suffix=".db")
    import config as _cfg
    _orig = _cfg.DB_PATH
    _cfg.DB_PATH = tmp

    print("🔧 در حال ساخت جداول در دیتابیس آزمایشی...")
    init_db()
    print("✅ جداول با موفقیت ساخته شدند.")

    conn = get_connection()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print(f"📋 جداول موجود: {[t['name'] for t in tables]}")

    p_count = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
    f_count = conn.execute("SELECT COUNT(*) FROM fillers").fetchone()[0]
    print(f"📊 P-Numberهای seed: {p_count} عدد | F-Numberهای seed: {f_count} عدد")
    conn.close()

    _cfg.DB_PATH = _orig
    os.remove(tmp)
    print("🧹 دیتابیس آزمایشی پاک شد.")
