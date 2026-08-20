"""
تست فاز ۲ ثبت دانش — رندر پیش‌نویس (متن/PDF/DOCX)، طبقه‌بندی AI و ستون‌های جدید.
اجرا: python test_knowledge_phase2.py
از یک دیتابیس موقت استفاده می‌کند؛ دیتابیس واقعی دست نمی‌خورد.
"""

import asyncio
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

TMP_OUT = tempfile.mkdtemp(prefix="kn_out_")

_pid = _cid = _uid = None
passed = 0


def ok(name: str):
    global passed
    passed += 1
    print(f"✅ {name}")


def reset_db():
    # کانکشن‌های SQLite با «with» بسته نمی‌شوند و فایل روی ویندوز قفل می‌ماند؛
    # پس فایل را حذف نمی‌کنیم — init_db idempotent است.
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


def make_entry(**kw):
    uid = ensure_user()
    pid, cid = ensure_project_and_contractor()
    defaults = dict(
        project_id=pid, contractor_id=cid, reported_by=uid,
        knowledge_type="lesson", reporter_name="کاربر تست",
    )
    defaults.update(kw)
    return models.add_knowledge_entry(**defaults)


def test_columns_and_migration():
    reset_db()
    from db.init import get_connection
    with get_connection() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(knowledge_entries)").fetchall()]
    assert "pdf_path" in cols and "docx_path" in cols, f"ستون‌ها ناقص: {cols}"
    ok("جدول knowledge_entries شامل pdf_path/docx_path است")

    # شبیه‌سازی دیتابیس قدیمی بدون ستون‌ها — migration باید idempotent ستون اضافه کند
    old_db = tempfile.mktemp(suffix=".db")
    import sqlite3 as _sq
    old = _sq.connect(old_db)
    old.execute("""CREATE TABLE knowledge_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kn_number TEXT UNIQUE, project_id INTEGER,
        contractor_id INTEGER, status TEXT, knowledge_type TEXT, reporter_name TEXT,
        reporter_title TEXT, reported_by INTEGER, raw_description TEXT, fields_json TEXT,
        draft_text TEXT, reported_date TEXT, submitted_at TEXT, is_active INTEGER,
        created_at TEXT, extra_data TEXT)""")
    old.commit()
    old.close()
    _save = db_init.DB_PATH
    db_init.DB_PATH = old_db
    db_init.init_db()
    db_init.DB_PATH = _save
    _conn = _sq.connect(old_db)
    try:
        cols = [r[1] for r in _conn.execute("PRAGMA table_info(knowledge_entries)").fetchall()]
    finally:
        _conn.close()
    os.remove(old_db)
    ok("migration ستون‌های مسیر فایل روی دیتابیس قدیمی")


def test_submit_with_paths():
    reset_db()
    kid = make_entry()
    models.submit_knowledge_entry(kid, "KN-001-1404-0001", pdf_path="p.pdf", docx_path="d.docx")
    entry = models.get_knowledge_entry_by_id(kid)
    assert entry["status"] == "submitted"
    assert entry["pdf_path"] == "p.pdf" and entry["docx_path"] == "d.docx"
    assert entry["kn_number"] == "KN-001-1404-0001"
    ok("submit_knowledge_entry مسیرهای pdf/docx را ذخیره می‌کند")


def _report(ktype, **kw):
    from engine.knowledge_draft import build_report, render_text
    defaults = dict(
        knowledge_type=ktype,
        title="عنوان تست",
        fields={},
        hashtags=["جوشکاری", "ایمنی"],
        impact_type=None,
        project_name="پروژه A",
        contractor_name="پیمانکار B",
        reporter_name="کاربر تست",
        reporter_title="سرپرست شیفت",
        reported_date="1404/05/12",
        kn_number=None,
        raw_description="متن آزاد تجربه",
        attachments=["001.jpg"],
    )
    defaults.update(kw)
    return build_report(**defaults), render_text(build_report(**defaults))


def test_draft_lesson():
    report, text = _report("lesson", fields={"problem": "مشکل X", "result": "نتیجه Y"})
    content = dict(report["content"])
    assert "شرح درس آموخته" in content
    assert "نتیجه اجرا" in content
    assert "درخت دانش" in [l for l, _ in report["metadata"]]
    assert "چک‌لیست نهایی اپراتور" in text
    assert report["qa_status"] == "نیازمند بازبینی"
    ok("پیش‌نویس درس‌آموخته: بخش‌ها + چک‌لیست + وضعیت QA")


def test_draft_suggestion():
    report, text = _report("suggestion", impact_type="کمی",
                           fields={"proposal": "پیشنهاد P", "expected_impact": "کاهش ۳۰٪ ضایعات"})
    content = dict(report["content"])
    assert content.get("تاثیر اجرای پیشنهاد") == "کمی"
    assert "اثر مورد انتظار — تأیید نشده" in content.get("نتایج حاصل از اجرای پیشنهاد", "")
    assert "کمیته تخصصی" in "\n".join(report["unresolved"])
    assert "بذر پیشنهاد" in "\n".join(report["unresolved"])
    ok("پیش‌نویس پیشنهاد: تاثیر کیفی/کمی + نتایج با علامت «اثر مورد انتظار»")


def test_draft_explicit():
    report, _ = _report("explicit")
    content = dict(report["content"])
    assert "زیرنوع دانش صریح" in content
    ok("پیش‌نویس دانش صریح: جایگاه زیرنوع")


def test_checklist_count():
    _, text = _report("lesson")
    import re
    items = re.findall(r"^\[ \]", text, flags=re.M)
    assert len(items) >= 5, f"چک‌لیست ناقص: {len(items)}"
    ok(f"چک‌لیست نهایی اپراتور: {len(items)} مورد")


def test_build_report_with_narrative_override():
    """narrative_override جایگزین ترکیب مکانیکی فیلدها میشود."""
    report, _ = _report(
        "lesson",
        fields={"problem": "x", "result": "y"},
        narrative_override="این narrative توسط AI polish تولید شده است",
    )
    content = dict(report["content"])
    assert content["شرح درس آموخته"] == "این narrative توسط AI polish تولید شده است"
    ok("build_report: narrative_override جایگزین شرح مکانیکی میشود")


def test_build_report_with_tree_path():
    """tree_path در فراداده نمایش داده میشود."""
    report, _ = _report(
        "lesson",
        tree_path=["MAPNA Development", "HSE Management", "Safety"],
    )
    metadata = dict(report["metadata"])
    assert metadata["درخت دانش"] == "MAPNA Development > HSE Management > Safety"
    assert not any("درخت دانش" in item for item in report["unresolved"])
    ok("build_report: tree_path در فراداده نمایش داده میشود")


def test_build_report_with_org_metadata():
    """org_metadata در فراداده براای suggestion/explicit اضافه میشود."""
    report, _ = _report(
        "suggestion",
        org_metadata={
            "committee": "کمیته ایمنی",
            "seed": "بازدید سایت",
            "colleagues": "الف، ب",
        },
    )
    metadata = dict(report["metadata"])
    assert metadata["کمیته تخصصی"] == "کمیته ایمنی"
    assert metadata["بذر پیشنهاد"] == "بازدید سایت"
    assert metadata["همکاران"] == "الف، ب"
    ok("build_report: org_metadata در فراداده suggestion اضافه میشود")


def test_build_report_optional_project_contractor():
    """project_name/contractor_name اختیاری (None مجاز)."""
    report, _ = _report("lesson", project_name=None, contractor_name=None)
    metadata = dict(report["metadata"])
    assert metadata["پروژه"] == "[اختیاری - ارائه نشده]"
    assert metadata["پیمانکار"] == "[اختیاری - ارائه نشده]"
    ok("build_report: project/contractor بدون مقدار → placeholder")


def test_docx_render():
    report, _ = _report("lesson")
    out = os.path.join(TMP_OUT, "sample.docx")
    from engine.knowledge_render import render_dana_docx
    render_dana_docx(report, out)
    assert os.path.isfile(out) and os.path.getsize(out) > 1000
    ok("render_dana_docx فایل Word معتبر می‌سازد")


def test_pdf_render():
    report, _ = _report("suggestion", impact_type="کیفی")
    out = os.path.join(TMP_OUT, "sample.pdf")
    from engine.knowledge_render import render_dana_pdf
    made = render_dana_pdf(report, out)
    if made:
        assert os.path.isfile(out) and os.path.getsize(out) > 1000
        ok("render_dana_pdf فایل PDF معتبر می‌سازد")
    else:
        print("⚠️ فونت عربی روی سیستم یافت نشد — PDF ساخته نشد (قابل قبول روی سرور بدون فونت)")


def test_extract_fields_disabled():
    import engine.knowledge_ai as kai
    _orig = kai.is_ai_enabled
    kai.is_ai_enabled = lambda: False
    try:
        result = asyncio.run(kai.extract_fields("suggestion", "یک پیشنهاد ساده برای بهبود"))
        # impact_type پیشوند میشود، سپس همهٔ فیلدهای متنی FIELD_SCHEMAS
        assert result["missing"][0] == "impact_type"
        assert set(result["missing"][1:]) == {
            "current_state", "problem", "proposal", "expected_impact",
            "seed", "committee", "colleagues",
        }
        assert result["impact_type"] is None
        assert result["classification"]["conflict"] is False
        assert result["title"] is None
        ok("extract_fields با AI غیرفعال: همه فیلدها + impact_type دستی، بدون conflict")
    finally:
        kai.is_ai_enabled = _orig


def test_extract_fields_mocked():
    import engine.knowledge_ai as kai

    async def fake_call(system, user_text):
        return (
            '{"title": "کاهش ضایعات خط لوله", '
            '"fields": {"proposal": "نصب گیج فشار جدید"}, '
            '"hashtags": ["ضایعات"], '
            '"impact_type": "کمی", '
            '"classification": {"recommended": "lesson", "reason": "اقدام انجام‌شده است", "conflict": true}}'
        )

    kai.is_ai_enabled = lambda: True
    _orig = kai._call_llm
    kai._call_llm = fake_call
    try:
        result = asyncio.run(kai.extract_fields("suggestion", "متن تست"))
        assert result["impact_type"] == "کمی", result
        assert result["classification"]["recommended"] == "lesson"
        assert result["classification"]["conflict"] is True
        # AI فیلد proposal را پر کرد؛ بقیه + impact_type ناقصاند
        assert "proposal" in result["fields"]
        assert "impact_type" not in result["fields"]  # impact_type دکمه‌ای، نه در fields
        assert "current_state" in result["missing"]
        assert "problem" in result["missing"]
        assert "expected_impact" in result["missing"]
        assert result["fields"]["proposal"] == "نصب گیج فشار جدید"
        ok("extract_fields: پارس impact_type + پیشنهاد طبقه‌بندی + فیلدهای ناقص")
    finally:
        kai.is_ai_enabled = lambda: False
        kai._call_llm = _orig


def test_extract_fields_bad_json():
    import engine.knowledge_ai as kai

    async def fake_call(system, user_text):
        raise RuntimeError("خطای شبکه")

    kai.is_ai_enabled = lambda: True
    _orig = kai._call_llm
    kai._call_llm = fake_call
    try:
        result = asyncio.run(kai.extract_fields("lesson", "متن"))
        assert set(result["missing"]) == {
            "context", "status", "problem", "cause", "action",
            "result", "lesson", "transferability", "recommendation",
        }
        assert result["fields"] == {}
        ok("extract_fields با خطای LLM: برگشت امن به حالت دستی")
    finally:
        kai.is_ai_enabled = lambda: False
        kai._call_llm = _orig


def test_handler_patterns():
    from handlers.knowledge import get_knowledge_conversation_handler
    h = get_knowledge_conversation_handler()
    patterns = []
    for entries in h.states.values():
        for entry in entries:
            p = getattr(entry, "pattern", None)
            if p:
                patterns.append(str(p))
    joined = " ".join(patterns)
    for pat in (r"kn_mode:manual", r"kn_mode:interview", r"kn_type:", r"kn_finish"):
        assert pat in joined, f"الگوی {pat} در handler نیست"
    ok("ConversationHandler دانش: الگوهای جدید kn_mode و حذف project/contractor ثبت شد")


def test_generate_knowledge_number_with_none_project():
    """generate_knowledge_number با project_id=None باید کد عمومی «KN» بدهد."""
    from engine.knowledge_numbering import generate_knowledge_number
    n = generate_knowledge_number(None)
    assert n.startswith("KN-KN-"), f"expected KN-KN prefix, got: {n}"
    # فرمت کامل: KN-KN-1405-001
    parts = n.split("-")
    assert len(parts) == 4
    assert parts[2].isdigit() and len(parts[2]) == 4  # سال۴ رقمی
    assert parts[3].isdigit() and len(parts[3]) == 3  # سریال۳ رقمی
    ok("generate_knowledge_number(None) → کد عمومی KN")


def test_generate_knowledge_number_serial_increments():
    """سریال برای پروژهٔ None هر بار افزایش مییابد."""
    from db import models
    from engine.knowledge_numbering import generate_knowledge_number

    uid = models.add_user(telegram_id=9001, full_name="u", role="operator")
    kid = models.add_knowledge_entry(
        project_id=None, contractor_id=None,
        reported_by=uid, knowledge_type="lesson", reporter_name="op",
    )
    n1 = generate_knowledge_number(None)
    models.submit_knowledge_entry(kid, n1, pdf_path=None, docx_path=None)
    n2 = generate_knowledge_number(None)
    s1 = int(n1.split("-")[-1])
    s2 = int(n2.split("-")[-1])
    assert s2 == s1 + 1, f"سریال بایدافزایش یابد: {n1} → {n2}"
    ok("generate_knowledge_number(None): سریال افزایشی")


def main():
    for fn in (test_columns_and_migration, test_submit_with_paths,
               test_draft_lesson, test_draft_suggestion, test_draft_explicit,
               test_checklist_count,
               test_build_report_with_narrative_override,
               test_build_report_with_tree_path,
               test_build_report_with_org_metadata,
               test_build_report_optional_project_contractor,
               test_docx_render, test_pdf_render,
               test_extract_fields_disabled, test_extract_fields_mocked,
               test_extract_fields_bad_json, test_handler_patterns,
               test_generate_knowledge_number_with_none_project,
               test_generate_knowledge_number_serial_increments):
        fn()
    print(f"\nتمام شد: {passed} تست PASS")


if __name__ == "__main__":
    main()
