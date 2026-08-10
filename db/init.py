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


def _migrate_project_contractor_m2m(cur) -> None:
    """
    اگر ستون قدیمی projects.contractor_id هنوز وجود دارد:
      ۱. جدول رابط project_contractors را می‌سازد
      ۲. داده‌های موجود را از contractor_id به جدول رابط منتقل می‌کند
      ۳. جدول projects را بدون contractor_id بازسازی می‌کند
    idempotent است — اجرای مکرر بی‌خطر است.
    """
    cols = [row[1] for row in cur.execute("PRAGMA table_info(projects)").fetchall()]
    if "contractor_id" not in cols:
        return

    # موقتاً بررسی FK را خاموش می‌کنیم — چون در ادامه جدول projects قدیمی
    # DROP می‌شود در حالی که project_contractors تازه‌ساخته به آن اشاره دارد
    cur.execute("PRAGMA foreign_keys = OFF")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_contractors (
            project_id     INTEGER NOT NULL REFERENCES projects(id),
            contractor_id  INTEGER NOT NULL REFERENCES contractors(id),
            PRIMARY KEY (project_id, contractor_id)
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO project_contractors (project_id, contractor_id)
        SELECT id, contractor_id FROM projects WHERE contractor_id IS NOT NULL
    """)

    cur.execute("""
        CREATE TABLE projects_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL UNIQUE,
            is_active       INTEGER NOT NULL DEFAULT 1
                            CHECK (is_active IN (0, 1)),
            created_at      TEXT    NOT NULL
        )
    """)
    cur.execute("""
        INSERT INTO projects_new (id, name, is_active, created_at)
        SELECT id, name, is_active, created_at FROM projects
    """)
    cur.execute("DROP TABLE projects")
    cur.execute("ALTER TABLE projects_new RENAME TO projects")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_project_contractors_contractor
        ON project_contractors(contractor_id)
    """)

    cur.execute("PRAGMA foreign_keys = ON")

# ══════════════════════════════════════════════════════════════════════════════
# این تابع را در db/init.py اضافه کنید — درست بعد از تعریف
# _migrate_project_contractor_m2m (نه قبلش، چون به جدول project_contractors
# که آن تابع می‌سازد وابسته است).
#
# دلیل نیاز به migration:
#   جدول فعلی project_contractors کلید ترکیبی (project_id, contractor_id)
#   دارد — یعنی فقط یک رکورد برای هر جفت پروژه/پیمانکار ممکن است. برای
#   پشتیبانی از «خاتمه در یک پروژه» + «الحاق مجدد با برچسب» به این‌ها نیاز داریم:
#     - id مستقل (چون باید چند رکورد تاریخی برای یک جفت مجاز باشد)
#     - status (active / pending_termination / terminated)
#     - label (متن آزاد — «الحاقیه»، «فاز ۲» و...)
#     - ردیابی درخواست/تأیید/رد خاتمه
#
#   محدودیت «فقط یک لینک فعال برای هر جفت» با partial UNIQUE INDEX
#   (WHERE status='active') در سطح دیتابیس تضمین می‌شود — نه فقط منطق پایتون.
#
# idempotent است — بررسی می‌کند ستون id از قبل هست یا نه، اجرای مکرر بی‌خطر.
# ══════════════════════════════════════════════════════════════════════════════

def _migrate_project_contractors_lifecycle(cur) -> None:
    """
    جدول project_contractors را از کلید ترکیبی ساده به مدل چرخهٔ‌حیات‌دار
    (وضعیت/برچسب/تاریخچه) ارتقا می‌دهد. idempotent.
    """
    cols = [row[1] for row in cur.execute("PRAGMA table_info(project_contractors)").fetchall()]
    if "id" in cols:
        return  # قبلاً migrate شده

    cur.execute("PRAGMA foreign_keys = OFF")

    cur.execute("""
        CREATE TABLE project_contractors_new (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id                  INTEGER NOT NULL REFERENCES projects(id),
            contractor_id               INTEGER NOT NULL REFERENCES contractors(id),
            label                       TEXT,
            status                      TEXT NOT NULL DEFAULT 'active'
                                        CHECK (status IN ('active', 'pending_termination', 'terminated')),
            linked_by                   INTEGER,
            linked_at                   TEXT NOT NULL,
            termination_requested_by    INTEGER,
            termination_requested_at    TEXT,
            terminated_by               INTEGER,
            terminated_at               TEXT,
            reject_reason               TEXT
        )
    """)

    # انتقال رکوردهای موجود — همه به‌عنوان لینک «فعال» با تاریخ لینک نامعلوم
    # (چون جدول قدیمی هیچ ستون تاریخی نداشت). این تنها فرض معقول است؛
    # اگر می‌خواهید تاریخ دقیق‌تری ثبت شود باید دستی روی رکوردهای قدیمی اصلاح کنید.
    cur.execute("""
        INSERT INTO project_contractors_new
            (project_id, contractor_id, status, linked_at)
        SELECT project_id, contractor_id, 'active', datetime('now')
        FROM project_contractors
    """)

    cur.execute("DROP TABLE project_contractors")
    cur.execute("ALTER TABLE project_contractors_new RENAME TO project_contractors")

    # فقط یک لینک «فعال» برای هر جفت پروژه/پیمانکار مجاز است —
    # لینک‌های terminated متعدد برای همان جفت (تاریخچهٔ الحاق/خاتمه) مجاز است.
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_project_contractors_active_unique
        ON project_contractors(project_id, contractor_id)
        WHERE status = 'active'
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_project_contractors_contractor
        ON project_contractors(contractor_id)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_project_contractors_project
        ON project_contractors(project_id)
    """)

    # برای صف درخواست‌های در انتظار تأیید سطح ۱
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_project_contractors_pending
        ON project_contractors(status)
        WHERE status = 'pending_termination'
    """)

    cur.execute("PRAGMA foreign_keys = ON")


# ══════════════════════════════════════════════════════════════════════════════
# نقطهٔ فراخوانی — در init_db()، بلافاصله بعد از خط زیر اضافه کنید:
#
#     _migrate_project_contractor_m2m(cur)
#     _migrate_project_contractors_lifecycle(cur)   # 🆕 همین خط را اضافه کنید
#
# ══════════════════════════════════════════════════════════════════════════════

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

        # ── migration: تبدیل رابطه projects/contractors به چند-به-چند (فاز ۸) ─
        _migrate_project_contractor_m2m(cur)
        _migrate_project_contractors_lifecycle(cur)

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

        # ── جدول pending_users (فاز ۸) ───────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pending_users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id     INTEGER NOT NULL UNIQUE,
                full_name       TEXT    NOT NULL,
                username        TEXT,
                first_seen_at   TEXT    NOT NULL,
                last_seen_at    TEXT    NOT NULL
            )
        """)

        # ── جدول access_grants (فاز ۸) ───────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS access_grants (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id     INTEGER NOT NULL,
                level           INTEGER NOT NULL
                                CHECK (level IN (1, 2, 3)),
                project_id      INTEGER
                                REFERENCES projects(id),
                contractor_id   INTEGER
                                REFERENCES contractors(id),
                granted_by      INTEGER NOT NULL,
                granted_at      TEXT    NOT NULL,
                is_active       INTEGER NOT NULL DEFAULT 1
                                CHECK (is_active IN (0, 1))
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_access_grants_telegram ON access_grants(telegram_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_access_grants_project ON access_grants(project_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_access_grants_contractor ON access_grants(contractor_id)")

        # ── جدول ncrs (فاز NCR — گزارش عدم انطباق) ────────────────────────
        # هر ردیف = یک فرم NCR با چرخه‌حیات draft → submitted.
        # فیلدهای انعطاف‌پذیر آینده در extra_data (JSON) ذخیره می‌شوند.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ncrs (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                ncr_number           TEXT UNIQUE,
                project_id           INTEGER NOT NULL REFERENCES projects(id),
                contractor_id        INTEGER NOT NULL REFERENCES contractors(id),
                status               TEXT NOT NULL DEFAULT 'draft'
                                     CHECK (status IN ('draft', 'submitted')),
                island               TEXT,
                unit                 TEXT,
                operation_type       TEXT,
                discipline           TEXT,
                drawing_number       TEXT,
                description          TEXT,
                cause                TEXT,
                corrective_action    TEXT,
                hse_confirmed        INTEGER
                                     CHECK (hse_confirmed IN (0, 1)),
                equipment_description TEXT,
                reporter_name        TEXT NOT NULL,
                reporter_title       TEXT,
                reported_by          INTEGER NOT NULL REFERENCES users(id),
                reported_date        TEXT,
                submitted_at         TEXT,
                excel_path           TEXT,
                is_active            INTEGER NOT NULL DEFAULT 1
                                     CHECK (is_active IN (0, 1)),
                created_at           TEXT NOT NULL,
                extra_data           TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ncrs_project ON ncrs(project_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ncrs_status ON ncrs(status)")

        # ── جدول عکس‌های NCR ──────────────────────────────────────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ncr_photos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ncr_id       INTEGER NOT NULL REFERENCES ncrs(id),
                path         TEXT NOT NULL,
                uploaded_at  TEXT NOT NULL
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ncr_photos_ncr ON ncr_photos(ncr_id)")

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
