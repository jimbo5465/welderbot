"""
تست توابع جدید DB برای فاز۳ — interview_history / tree_path / org_metadata / resume.
اجرا: python test_knowledge_db_helpers.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
import db.init as db_init
from db import models

TMP_DB = tempfile.mktemp(suffix=".db")
cfg.DB_PATH = TMP_DB
db_init.DB_PATH = TMP_DB
db_init.init_db()

passed = 0


def ok(name: str):
    global passed
    passed += 1
    print(f"✅ {name}")


_uid = None


def _uid_():
    global _uid
    if _uid is None:
        _uid = models.add_user(telegram_id=7001, full_name="کاربر تست", role="operator")
    return _uid


def _make_entry(kn_kwargs=None):
    """رکورد میسازد و submit میکند — pending نیست، pending-ها را خراب نمیکند."""
    kid = models.add_knowledge_entry(
        project_id=None, contractor_id=None,
        reported_by=_uid_(), knowledge_type="lesson",
        reporter_name="op", **({"raw_description": "شروع شده"} if kn_kwargs is None else kn_kwargs),
    )
    models.submit_knowledge_entry(kid, f"KN-001-1404-{kid:04d}")
    return kid


def _make_pending_entry(telegram_id: int, raw_text: str = "شرح") -> int:
    """رکورد draft ناتمام برای یک کاربر خاص میسازد (برای تست‌های find_pending)."""
    user = models.get_user_by_telegram_id(telegram_id)
    if user is None:
        uid = models.add_user(telegram_id=telegram_id, full_name="t", role="operator")
    else:
        uid = user["id"]
    return models.add_knowledge_entry(
        project_id=None, contractor_id=None,
        reported_by=uid, knowledge_type="lesson",
        reporter_name="op", raw_description=raw_text,
    )


def test_interview_history_set_get():
    kid = _make_entry()
    models.set_knowledge_interview_history(kid, [{"role": "user", "content": "سلام"}])
    hist = models.get_knowledge_interview_history(kid)
    assert hist == [{"role": "user", "content": "سلام"}]
    models.set_knowledge_interview_history(kid, [])
    assert models.get_knowledge_interview_history(kid) == []
    ok("interview_history: set + get + clear")


def test_tree_path_set_get():
    kid = _make_entry()
    path = ["MAPNA Development", "HSE Management", "Safety"]
    models.set_knowledge_tree_path(kid, path)
    assert models.get_knowledge_tree_path(kid) == path
    models.set_knowledge_tree_path(kid, [])
    assert models.get_knowledge_tree_path(kid) == []
    ok("tree_path: set + get + clear")


def test_org_metadata_set_get():
    kid = _make_entry()
    org = {"committee": "کمیته ایمنی", "seed": "ایده از بازدید سایت", "colleagues": "الف، ب"}
    models.set_knowledge_org_metadata(kid, org)
    assert models.get_knowledge_org_metadata(kid) == org
    models.set_knowledge_org_metadata(kid, {})
    assert models.get_knowledge_org_metadata(kid) == {}
    ok("org_metadata: set + get + clear")


def test_find_pending_returns_unfinished():
    """رکورد draft بدون kn_number و با raw_description → پیدا میشود."""
    tg = 8001
    kid = _make_pending_entry(tg, "شرح اولیه")
    found = models.find_pending_knowledge_by_user(tg)
    assert found is not None
    assert found["id"] == kid
    assert found["status"] == "draft"
    assert found["kn_number"] is None
    ok("find_pending: رکورد draft ناتمام را پیدا میکند")


def test_find_pending_ignores_finished():
    """رکورد submitted نباید در نتایج باشد."""
    tg = 8002
    kid = _make_pending_entry(tg)
    models.submit_knowledge_entry(kid, f"KN-001-1404-{kid:04d}")
    assert models.find_pending_knowledge_by_user(tg) is None
    ok("find_pending: رکورد ثبت‌شده (submitted) را نادیده میگیرد")


def test_find_pending_ignores_empty_drafts():
    """رکورد draft بدون هیچ داده (خالی) → پیدا نشود."""
    tg = 8003
    user = models.get_user_by_telegram_id(tg)
    if user is None:
        user_id = models.add_user(telegram_id=tg, full_name="t", role="operator")
    else:
        user_id = user["id"]
    models.add_knowledge_entry(
        project_id=None, contractor_id=None,
        reported_by=user_id,
        knowledge_type="lesson", reporter_name="op",
    )
    assert models.find_pending_knowledge_by_user(tg) is None
    ok("find_pending: draft خالی (بدون شرح و مصاحبه) را نادیده میگیرد")


def test_find_pending_with_interview_history():
    """رکورد draft با interview_history_json → پیدا میشود."""
    tg = 8004
    kid = _make_pending_entry(tg, "")
    models.set_knowledge_interview_history(kid, [{"role": "user", "content": "پاسخ"}])
    found = models.find_pending_knowledge_by_user(tg)
    assert found is not None
    assert found["id"] == kid
    ok("find_pending: draft با interview_history (بدون raw_description) پیدا میشود")


def test_find_pending_returns_most_recent():
    """اگر چند رکورد ناتمام باشد، آخری برگردد."""
    tg = 8005
    kid1 = _make_pending_entry(tg, "اول")
    import time
    time.sleep(1.1)
    kid2 = _make_pending_entry(tg, "دوم")
    found = models.find_pending_knowledge_by_user(tg)
    assert found["id"] == kid2, f"باید kid2 برگردد ولی {found['id']}"
    ok("find_pending: در چند رکورد ناتمام، آخری برمیگردد")


def test_find_pending_no_match_other_user():
    """اگر کاربر دیگری رکورد ناتمام داشته باشد، پیدا نشود."""
    tg1, tg2 = 8006, 8007
    kid1 = _make_pending_entry(tg1, "شرح من")
    kid2 = _make_pending_entry(tg2, "شرح دیگری")
    found1 = models.find_pending_knowledge_by_user(tg1)
    found2 = models.find_pending_knowledge_by_user(tg2)
    assert found1["id"] == kid1
    assert found2["id"] == kid2
    ok("find_pending: تفکیک بر اساس کاربر (telegram_id)")


def main():
    for fn in (
        test_interview_history_set_get,
        test_tree_path_set_get,
        test_org_metadata_set_get,
        test_find_pending_returns_unfinished,
        test_find_pending_ignores_finished,
        test_find_pending_ignores_empty_drafts,
        test_find_pending_with_interview_history,
        test_find_pending_returns_most_recent,
        test_find_pending_no_match_other_user,
    ):
        fn()
    print(f"\nتمام شد: {passed} تست PASS")


if __name__ == "__main__":
    main()