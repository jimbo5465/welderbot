"""
تست فاز۳ دانش — DB migration به schema جدید (nullable FK + ستونهای جدید).
اجرا: python test_knowledge_phase3.py
از یک دیتابیس موقت استفاده میکند؛ دیتابیس واقعی دست نمیخورد.
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import db.init as db_init
from db import models

TMP_DB = tempfile.mktemp(suffix=".db")
_ORIG_DB = cfg.DB_PATH
cfg.DB_PATH = TMP_DB
db_init.DB_PATH = TMP_DB

passed = 0


def ok(name: str):
    global passed
    passed += 1
    print(f"✅ {name}")


def _table_info(db_path: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("PRAGMA table_info(knowledge_entries)").fetchall()
    finally:
        conn.close()


def test_fresh_db_has_new_schema():
    """DB تازه باید ستونهای جدید و FK های nullable را داشته باشد."""
    if os.path.exists(TMP_DB):
        os.remove(TMP_DB)
    db_init.init_db()
    cols = _table_info(TMP_DB)
    by_name = {c[1]: c for c in cols}
    # nullable FK
    assert by_name["project_id"][3] == 0, "project_id باید nullable باشد"
    assert by_name["contractor_id"][3] == 0, "contractor_id باید nullable باشد"
    # ستونهای جدید
    for new_col in ("interview_history_json", "tree_path_json", "org_metadata_json"):
        assert new_col in by_name, f"ستون {new_col} وجود ندارد"
    ok("DB تازه: FK ها nullable + ۳ ستون جدید")


def test_add_knowledge_without_project():
    """ثبت دانش بدون project_id و contractor_id باید موفق باشد."""
    uid = models.add_user(telegram_id=2001, full_name="اپراتور تست", role="operator")
    kid = models.add_knowledge_entry(
        project_id=None,
        contractor_id=None,
        reported_by=uid,
        knowledge_type="lesson",
        reporter_name="اپراتور",
    )
    entry = models.get_knowledge_entry_by_id(kid)
    assert entry is not None
    assert entry["project_id"] is None
    assert entry["contractor_id"] is None
    ok("ثبت دانش بدون project_id/contractor_id موفق")


def test_migrate_old_preserves_data():
    """DB قدیمی (با NOT NULL FK و بدون ستون جدید) باید به schema جدید migrate شود؛ داده حفظ شود."""
    old_db = tempfile.mktemp(suffix=".db")
    sq = sqlite3.connect(old_db)
    sq.executescript("""
        CREATE TABLE projects (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE contractors (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, telegram_id INTEGER NOT NULL UNIQUE,
            full_name TEXT NOT NULL, role TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE knowledge_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kn_number TEXT UNIQUE,
            project_id INTEGER NOT NULL REFERENCES projects(id),
            contractor_id INTEGER NOT NULL REFERENCES contractors(id),
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','submitted')),
            knowledge_type TEXT NOT NULL
                CHECK (knowledge_type IN ('lesson','suggestion','explicit')),
            reporter_name TEXT NOT NULL, reporter_title TEXT,
            reported_by INTEGER NOT NULL REFERENCES users(id),
            raw_description TEXT, fields_json TEXT, draft_text TEXT,
            reported_date TEXT, submitted_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
            created_at TEXT NOT NULL, extra_data TEXT
        );
        INSERT INTO projects VALUES (1, 'پروژه قدیمی');
        INSERT INTO contractors VALUES (1, 'پیمانکار قدیمی');
        INSERT INTO users VALUES (1, 9999, 'old-user', 'operator', 1, '2024-01-01');
        INSERT INTO knowledge_entries (
            kn_number, project_id, contractor_id, knowledge_type,
            reporter_name, reported_by, created_at
        ) VALUES ('KN-001-1403-0001', 1, 1, 'lesson', 'گزارشگر قدیمی', 1, '2024-01-01');
    """)
    sq.commit()
    sq.close()

    # حالا init_db را روی این DB قدیمی اجرا کن (اما فقط migration دانش)
    _save = db_init.DB_PATH
    db_init.DB_PATH = old_db
    # بقیهٔ migration ها به جداول project_contractors نیاز دارند که در این DB تست
    # نیستند — پس آنها را موقتاً بیاثر میکنیم تا فقط _migrate_knowledge_phase3 اجرا شود
    _orig_lifecycle = db_init._migrate_project_contractors_lifecycle
    _orig_m2m = db_init._migrate_project_contractor_m2m
    db_init._migrate_project_contractors_lifecycle = lambda cur: None
    db_init._migrate_project_contractor_m2m = lambda cur: None
    try:
        db_init.init_db()
    finally:
        db_init._migrate_project_contractors_lifecycle = _orig_lifecycle
        db_init._migrate_project_contractor_m2m = _orig_m2m
        db_init.DB_PATH = _save

    cols = _table_info(old_db)
    by_name = {c[1]: c for c in cols}

    # بررسی: FK nullable
    assert by_name["project_id"][3] == 0
    assert by_name["contractor_id"][3] == 0
    # بررسی: ستونهای جدید
    for new_col in ("interview_history_json", "tree_path_json", "org_metadata_json"):
        assert new_col in by_name
    # بررس: داده حفظ شده
    sq2 = sqlite3.connect(old_db)
    try:
        row = sq2.execute("SELECT kn_number, project_id, contractor_id FROM knowledge_entries").fetchone()
    finally:
        sq2.close()
    assert row[0] == "KN-001-1403-0001"
    assert row[1] == 1
    assert row[2] == 1
    os.remove(old_db)
    ok("migration روی DB قدیمی: FK nullable + ستونهای جدید + داده حفظ شد")


def test_migration_is_idempotent():
    """اجرای مکرر migration نباید خطا بدهد یا داده را خراب کند."""
    db_init.init_db()  # DB فعلی از قبل schema جدید دارد
    db_init.init_db()  # اجرای دوم
    db_init.init_db()  # اجرای سوم
    cols = _table_info(TMP_DB)
    by_name = {c[1]: c for c in cols}
    assert by_name["project_id"][3] == 0
    assert "interview_history_json" in by_name
    ok("migration idempotent: اجرای مکرر بدون خطا")


def test_existing_phase2_tests_still_pass():
    """تستهای فاز۲ (submit با مسیر PDF/DOCX) هنوز باید کار کنند."""
    uid = models.add_user(telegram_id=3001, full_name="u3", role="operator")
    kid = models.add_knowledge_entry(
        project_id=None, contractor_id=None, reported_by=uid,
        knowledge_type="suggestion", reporter_name="op3",
        reporter_title="سرپرست",
    )
    models.submit_knowledge_entry(kid, "KN-001-1404-0002", pdf_path="p.pdf", docx_path="d.docx")
    entry = models.get_knowledge_entry_by_id(kid)
    assert entry["status"] == "submitted"
    assert entry["pdf_path"] == "p.pdf"
    assert entry["docx_path"] == "d.docx"
    assert entry["kn_number"] == "KN-001-1404-0002"
    ok("submit_knowledge_entry با مسیرهای PDF/DOCX همچنان کار میکند")


def main():
    for fn in (
        test_fresh_db_has_new_schema,
        test_add_knowledge_without_project,
        test_migrate_old_preserves_data,
        test_migration_is_idempotent,
        test_existing_phase2_tests_still_pass,
    ):
        fn()
    print(f"\nتمام شد: {passed} تست PASS")


if __name__ == "__main__":
    main()