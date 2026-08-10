"""
تست واحد فاز NCR — لایهٔ دیتابیس و شماره‌دهی.
اجرا: python test_ncr_phase1.py
از یک دیتابیس موقت استفاده می‌کند؛ دیتابیس واقعی دست نمی‌خورد.
"""

import os
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

_pid = None
_cid = None
_uid = None


def reset_db():
    if os.path.exists(TMP_DB):
        os.remove(TMP_DB)
    db_init.init_db()


def ensure_user():
    global _uid
    if _uid is None:
        _uid = models.add_user(telegram_id=1001, full_name="علی محمدی", role="admin")
    return _uid


def ensure_project_and_contractor():
    global _pid, _cid
    if _pid is None:
        _pid = models.add_project("نیروگاه سیکل ترکیبی شیراز")
        _cid = models.add_contractor("شرکت پارس نیرو")
        models.link_project_contractor(_pid, _cid)
    return _pid, _cid


def make_simple_ncr():
    uid = ensure_user()
    pid, cid = ensure_project_and_contractor()
    return models.add_ncr(
        project_id=pid, contractor_id=cid, reported_by=uid, reporter_name="کاربر تست"
    )


def test_table_creation():
    from db.init import get_connection
    with get_connection() as conn:
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
    assert "ncrs" in tables, "جدول ncrs ساخته نشد"
    assert "ncr_photos" in tables, "جدول ncr_photos ساخته نشد"
    print("✅ جداول ncrs و ncr_photos ساخته شدند")


def test_add_and_get_ncr():
    uid = ensure_user()
    pid, cid = ensure_project_and_contractor()

    ncr_id = models.add_ncr(
        project_id=pid,
        contractor_id=cid,
        reported_by=uid,
        reporter_name="مهندس رضایی",
        reporter_title="بازرس مکانیک",
        island="جزیره یک",
        unit="واحد ۱",
        operation_type="نصب",
        discipline="مکانیک",
        drawing_number="D-001",
        description="عدم انطباق در فیت‌آپ فلنج‌ها",
        cause="نصب",
        corrective_action="بازگشت سطح فلنج‌ها",
        hse_confirmed=1,
        equipment_description="تورک رنچ",
        reported_date="1404/05/12",
        extra_data={"orig": "sample"},
    )
    ncr = models.get_ncr_by_id(ncr_id)
    assert ncr is not None, "NCR ذخیره نشد"
    assert ncr["status"] == "draft"
    assert ncr["project_name"] == "نیروگاه سیکل ترکیبی شیراز"
    assert ncr["contractor_name"] == "شرکت پارس نیرو"
    assert ncr["extra_data"]["orig"] == "sample"
    assert ncr["description"].startswith("عدم انطباق")
    print(f"✅ add_ncr / get_ncr_by_id: id={ncr_id} status={ncr['status']}")


def test_update_and_submit():
    ncr_id = make_simple_ncr()
    models.update_ncr(ncr_id, {"description": "توضیح به‌روز شده", "unit": "واحد ۲"})
    ncr = models.get_ncr_by_id(ncr_id)
    assert ncr["description"] == "توضیح به‌روز شده"
    assert ncr["unit"] == "واحد ۲"

    from engine.ncr_numbering import generate_ncr_number
    pid = models.get_ncr_by_id(ncr_id)["project_id"]
    number = generate_ncr_number(pid)
    models.submit_ncr(ncr_id, number, "/tmp/ncr.xlsx")
    ncr = models.get_ncr_by_id(ncr_id)
    assert ncr["status"] == "submitted"
    assert ncr["ncr_number"] == number
    print(f"✅ update/submit: شماره اختصاص یافت: {number}")

    models.reopen_ncr(ncr_id)
    ncr = models.get_ncr_by_id(ncr_id)
    assert ncr["status"] == "draft"
    assert ncr["ncr_number"] is None
    print("✅ reopen به draft — OK")


def test_numbering_sequence():
    uid = ensure_user()
    pid, cid = ensure_project_and_contractor()
    from engine.ncr_numbering import generate_ncr_number

    n1 = generate_ncr_number(pid)
    models.submit_ncr(models.add_ncr(project_id=pid, contractor_id=cid, reported_by=uid, reporter_name="ت"), n1, "/tmp/a.xlsx")
    n2 = generate_ncr_number(pid)
    models.submit_ncr(models.add_ncr(project_id=pid, contractor_id=cid, reported_by=uid, reporter_name="ت"), n2, "/tmp/b.xlsx")
    n3 = generate_ncr_number(pid)
    assert len({n1, n2, n3}) == 3, (n1, n2, n3)
    assert n1.endswith("-001") and n2.endswith("-002") and n3.endswith("-003"), (n1, n2, n3)
    print(f"✅ شماره‌دهی ترتیبی: {n1} | {n2} | {n3}")


def test_photos():
    from db.init import get_connection
    ncr_id = make_simple_ncr()
    models.add_ncr_photo(ncr_id, "media/ncr_photos/1/a.jpg")
    models.add_ncr_photo(ncr_id, "media/ncr_photos/1/b.jpg")
    photos = models.list_ncr_photos(ncr_id)
    assert len(photos) == 2
    assert photos[0]["path"].endswith("a.jpg")
    print(f"✅ عکس‌ها ذخیره و خوانده شدند: {len(photos)} عکس")


def test_excel_build():
    """تولید فایل Excel NCR از روی یک رکورد نمونه — قالب باید موجود باشد."""
    from engine.ncr_excel import build_ncr_excel

    uid = ensure_user()
    pid, cid = ensure_project_and_contractor()
    ncr_id = models.add_ncr(
        project_id=pid,
        contractor_id=cid,
        reported_by=uid,
        reporter_name="مهندس رضایی",
        reporter_title="بازرس مکانیک",
        island="جزیره یک",
        unit="واحد ۱",
        operation_type="نصب",
        discipline="مکانیک",
        drawing_number="D-001",
        description="عدم انطباق در فیت‌آپ فلنج‌ها",
        cause="نصب",
        corrective_action="بازگشت سطح فلنج‌ها",
        hse_confirmed=1,
        equipment_description="تورک رنچ",
        reported_date="1404/05/12",
    )
    out = build_ncr_excel(ncr_id, "SHAZ-NCR-1404-001")
    assert os.path.isfile(out), f"فایل اکسل ساخته نشد: {out}"
    print(f"✅ Excel ساخته شد: {out}")


if __name__ == "__main__":
    reset_db()
    test_table_creation()
    test_add_and_get_ncr()
    test_update_and_submit()
    test_numbering_sequence()
    test_photos()
    test_excel_build()
    print("\n🎉 همهٔ تست‌های فاز ۱ پاس شدند.")

    if os.path.exists(TMP_DB):
        try:
            os.remove(TMP_DB)
        except PermissionError:
            pass  # کانکشن‌های باز sqlite روی ویندوز اجازهٔ حذف نمی‌دهند — مهم نیست
    cfg.DB_PATH = _ORIG_DB