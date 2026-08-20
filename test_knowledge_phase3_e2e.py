"""
تست E2E فاز۳ — جریان‌های یکپارچه ثبت دانش.
اجرا: python test_knowledge_phase3_e2e.py

این تست‌ها فراخوانی‌های AI را mock میکنند و مسیرهای مختلف را شبیه‌سازی میکنند.
هدف: verification اینکه اجزا با هم کار میکنند — DB + draft + render + polish + tree.
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
        _uid = models.add_user(telegram_id=30001, full_name="اپراتور تست", role="operator")
    return _uid


def test_method_1_full_flow_no_ai():
    """
    روش دستی بدون AI: ثبت دانش ساده با همه فیلدها پر شده.
    مسیر: add → set fields → build_report → render → submit → render files.
    """
    uid = _uid_()
    kid = models.add_knowledge_entry(
        project_id=None, contractor_id=None,
        reported_by=uid, knowledge_type="lesson",
        reporter_name="اپراتور", reporter_title="سرپرست",
        raw_description="شرح اولیه آزمایشی",
        reported_date="1404/05/12",
    )
    models.set_knowledge_fields(kid, {
        "context": "پروژه تست",
        "status": "در حال اجرا",
        "problem": "مشکل نمونه",
        "cause": "علت نمونه",
        "action": "اقدام نمونه",
        "result": "نتیجه نمونه",
        "lesson": "درس اصلی نمونه",
        "transferability": "در همه جا قابل اجراست",
        "recommendation": "توصیه نمونه",
    })
    fields = models.get_knowledge_entry_by_id(kid)["fields_json"]
    from engine.knowledge_draft import build_report, render_text
    report = build_report(
        knowledge_type="lesson",
        title="تست درس‌آموخته",
        fields=fields,
        hashtags=["a", "b"],
        impact_type=None,
        project_name=None,
        contractor_name=None,
        reporter_name="اپراتور",
        reporter_title="سرپرست",
        reported_date="1404/05/12",
    )
    draft = render_text(report)
    models.set_knowledge_fields(kid, fields, draft)

    from engine.knowledge_numbering import generate_knowledge_number
    number = generate_knowledge_number(None)

    import os
    from engine.knowledge_render import render_dana_pdf, render_dana_docx
    out_dir = os.path.join(cfg.KN_OUTPUT_PATH, str(kid))
    os.makedirs(out_dir, exist_ok=True)
    pdf_path = os.path.join(out_dir, f"{number}.pdf")
    docx_path = os.path.join(out_dir, f"{number}.docx")
    assert render_dana_pdf(report, pdf_path), "PDF ساخته نشد"
    render_dana_docx(report, docx_path)
    models.submit_knowledge_entry(kid, number, pdf_path=pdf_path, docx_path=docx_path)

    final = models.get_knowledge_entry_by_id(kid)
    assert final["status"] == "submitted"
    assert final["kn_number"] == number
    assert final["pdf_path"] == pdf_path
    assert final["docx_path"] == docx_path
    assert final["fields_json"]["lesson"] == "درس اصلی نمونه"
    assert os.path.isfile(pdf_path) and os.path.getsize(pdf_path) > 1000
    assert os.path.isfile(docx_path) and os.path.getsize(docx_path) > 1000
    ok("روش دستی: add → fields → report → submit → فایل‌ها تولید شدند")


def test_method_2_interview_flow_mocked():
    """
    روش مصاحبه: شبیهسازی حلقه با AI mock.
    """
    import engine.knowledge_ai as kai
    import engine.knowledge_interview as kiv

    call_count = [0]
    responses = [
        {"extracted": {"context": "پروژه تست"}, "ask": "چه مشکلی پیش آمد؟"},
        {"extracted": {"problem": "ترک در جوش"}, "ask": "چه اقدامی کردید؟"},
        {"extracted": {"action": "پیشگرم به 150 درجه"}, "ask": "نتیجه چه شد؟"},
        {"extracted": {"result": "ترک برطرف شد"}, "ask": "درس اصلی چیست؟"},
        {"extracted": {"lesson": "کنترل دما مهم است"}, "ask": "توصیه برای دیگران؟"},
        {
            "done": True,
            "fields": {
                "context": "پروژه تست", "problem": "ترک در جوش",
                "action": "پیشگرم", "result": "برطرف شد",
                "lesson": "کنترل دما",
            },
            "title": "درس کنترل دما",
            "summary": "تجربه موفق کنترل دمای پیشگرم",
        },
    ]

    async def fake(messages, **kw):
        idx = call_count[0]
        call_count[0] += 1
        import json
        return json.dumps(responses[min(idx, len(responses) - 1)])

    kiv.is_ai_enabled = lambda: True
    kiv._call_llm_messages = fake

    async def run():
        history = []
        fields = {}
        for i in range(6):
            user_msg = f"پاسخ {i}"
            result = await kiv.interview_next_turn("lesson", history, user_msg)
            history.append({"role": "user", "content": user_msg})
            if result.get("extracted"):
                fields.update(result["extracted"])
            if result.get("ask"):
                history.append({"role": "assistant", "content": result["ask"]})
            if result.get("done"):
                fields = result.get("fields") or fields
                break
        return fields, history

    fields, history = asyncio.run(run())
    assert call_count[0] >= 5, f"باید حداقل 5 بار AI صدا زده شود، اما {call_count[0]} بار"
    assert fields["lesson"] == "کنترل دما"
    assert fields["context"] == "پروژه تست"
    assert len(history) >= 10, "تاریخچه باید پر شود"
    ok("روش مصاحبه: حلقهٔ ۶ نوبت با AI mock، فیلدها جمع شدند")


def test_polish_with_mocked_ai():
    """
    polish_dana_draft با AI mock: narrative + hashtags + project extraction.
    """
    import engine.knowledge_ai as kai
    import engine.knowledge_interview as kiv

    async def fake(messages, **kw):
        return (
            '{"narrative": "narrative تمیز فارسی",'
            ' "extracted_project": "نیروگاه شیراز",'
            ' "extracted_contractor": null,'
            ' "hashtags": ["جوشکاری", "پیشگرم"],'
            ' "title_suggestion": null}'
        )

    kiv.is_ai_enabled = lambda: True
    kiv._call_llm_messages = fake

    result = asyncio.run(kiv.polish_dana_draft(
        "lesson",
        {"context": "...", "result": "موفق"},
        raw_description="در پروژه نیروگاه شیراز، مشکل ترک در جوش حل شد.",
    ))
    assert result["narrative"] == "narrative تمیز فارسی"
    assert result["extracted_project"] == "نیروگاه شیراز"
    assert result["hashtags"] == ["جوشکاری", "پیشگرم"]
    ok("polish با AI mock: narrative + project + hashtags استخراج شدند")


def test_suggest_tree_integration():
    """
    suggest_tree_paths → validate_path → set_knowledge_tree_path → get back.
    """
    import engine.knowledge_ai as kai
    import engine.knowledge_interview as kiv

    async def fake(messages, **kw):
        import json
        return json.dumps({
            "suggestions": [
                {"path": ["MAPNA Development", "Execution Management and Supervision", "Civil Works"],
                 "confidence": 0.78, "reason": "مربوط به اجرای سایت"},
                {"path": ["نود_نامعلوم", "x", "y"], "confidence": 0.5, "reason": "نامعتبر"},
            ]
        })

    kiv.is_ai_enabled = lambda: True
    kiv._call_llm_messages = fake

    suggestions = asyncio.run(kiv.suggest_tree_paths(
        "lesson", {"context": "..."}, "شرح", "عنوان", top_k=3,
    ))
    assert len(suggestions) == 1, f"نود نامعتبر باید فیلتر شود: {suggestions}"
    assert suggestions[0]["path"][-1] == "Civil Works"
    assert suggestions[0]["confidence"] == 0.78

    # ذخیره در DB
    uid = _uid_()
    kid = models.add_knowledge_entry(
        project_id=None, contractor_id=None,
        reported_by=uid, knowledge_type="lesson",
        reporter_name="op",
    )
    models.set_knowledge_tree_path(kid, suggestions[0]["path"])
    assert models.get_knowledge_tree_path(kid) == suggestions[0]["path"]
    ok("suggest_tree + DB persistence: مسیر معتبر ذخیره شد")


def test_org_metadata_persistence():
    """تنظیم org_metadata و خواندن از DB."""
    uid = _uid_()
    kid = models.add_knowledge_entry(
        project_id=None, contractor_id=None,
        reported_by=uid, knowledge_type="suggestion",
        reporter_name="op",
    )
    org = {
        "committee": "کمیته ایمنی",
        "seed": "بازدید سایت",
        "colleagues": "الف، ب، ج",
        "hashtags_override": ["ایمنی"],
    }
    models.set_knowledge_org_metadata(kid, org)
    got = models.get_knowledge_org_metadata(kid)
    assert got == org
    ok("org_metadata: در DB ذخیره و بازیابی شد")


def test_resume_full_cycle():
    """
    شبیهسازی کامل: ثبت → pause → find_pending → resume → ادامه.
    """
    uid = _uid_()
    # رکورد draft ناتمام
    kid1 = models.add_knowledge_entry(
        project_id=None, contractor_id=None,
        reported_by=uid, knowledge_type="lesson",
        reporter_name="op", raw_description="شرح اولیه",
    )
    models.set_knowledge_interview_history(kid1, [
        {"role": "user", "content": "پاسخ اول"},
        {"role": "assistant", "content": "سؤال بعدی"},
    ])

    # find_pending
    pending = models.find_pending_knowledge_by_user(30001)
    assert pending is not None
    assert pending["id"] == kid1
    assert models.get_knowledge_interview_history(kid1)

    # ادامه فرضی: ثبت فیلد جدید
    models.set_knowledge_fields(kid1, {"context": "پروژه ادامه"})

    # ثبت نهایی
    from engine.knowledge_numbering import generate_knowledge_number
    number = generate_knowledge_number(None)
    models.submit_knowledge_entry(kid1, number)

    # حالا دیگر pending نیست
    assert models.find_pending_knowledge_by_user(30001) is None
    ok("resume چرخهٔ کامل: draft → find_pending → ادامه → submit")


def test_method_2_persists_history_per_turn():
    """
    شبیهسازی هر نوبت مصاحبه که history در DB ذخیره شود.
    """
    import engine.knowledge_ai as kai
    import engine.knowledge_interview as kiv

    async def fake(messages, **kw):
        import json
        return json.dumps({"extracted": {"context": "تست"}, "ask": "بعدی؟"})

    kiv.is_ai_enabled = lambda: True
    kiv._call_llm_messages = fake

    uid = _uid_()
    kid = models.add_knowledge_entry(
        project_id=None, contractor_id=None,
        reported_by=uid, knowledge_type="lesson",
        reporter_name="op",
    )

    async def run():
        history = []
        for turn in range(3):
            user_msg = f"پاسخ {turn}"
            history.append({"role": "user", "content": user_msg})
            result = await kiv.interview_next_turn("lesson", history, user_msg)
            if result.get("ask"):
                history.append({"role": "assistant", "content": result["ask"]})
            # در handler واقعی، بعد از هر نوبت history ذخیره می‌شود
            models.set_knowledge_interview_history(kid, history)
            models.set_knowledge_fields(kid, result.get("extracted") or {})

    asyncio.run(run())

    saved = models.get_knowledge_interview_history(kid)
    assert len(saved) >= 6, f"تاریخچه باید حداقل 6 پیام داشته باشد، اما {len(saved)} دارد"
    ok("مصاحبه: history پس از هر نوبت در DB ذخیره میشود")


def main():
    for fn in (
        test_method_1_full_flow_no_ai,
        test_method_2_interview_flow_mocked,
        test_polish_with_mocked_ai,
        test_suggest_tree_integration,
        test_org_metadata_persistence,
        test_resume_full_cycle,
        test_method_2_persists_history_per_turn,
    ):
        fn()
    print(f"\nتمام شد: {passed} تست PASS")


if __name__ == "__main__":
    main()