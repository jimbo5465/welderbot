"""
تست فاز۳c — موتور مصاحبه + polish + tree suggestion.
اجرا: python test_knowledge_interview.py

AI در این تست‌ها mocked میشود (بدون فراخوانی واقعی).
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine.knowledge_ai as kai
import engine.knowledge_interview as kiv

passed = 0


def ok(name: str):
    global passed
    passed += 1
    print(f"✅ {name}")


def test_interview_framework_complete():
    """INTERVIEW_FRAMEWORKS همهٔ کلیدهای FIELD_SCHEMAS را شامل میشود."""
    for kt in ("lesson", "suggestion", "explicit"):
        fw = kiv.INTERVIEW_FRAMEWORKS.get(kt, [])
        schema_keys = set(kai.FIELD_SCHEMAS.get(kt, {}).keys())
        fw_keys = {k for k in fw if k in schema_keys}
        assert fw_keys == schema_keys, f"{kt}: framework {fw_keys} != schema {schema_keys}"
    ok("INTERVIEW_FRAMEWORKS همهٔ فیلدهای متنی FIELD_SCHEMAS را پوشش میدهد")


def test_interview_framework_includes_buttons():
    """INTERVIEW_FRAMEWORKS شامل فیلدهای دکمهای هم میشود."""
    assert "impact_type" in kiv.INTERVIEW_FRAMEWORKS["suggestion"]
    assert "subtype" in kiv.INTERVIEW_FRAMEWORKS["explicit"]
    ok("INTERVIEW_FRAMEWORKS شامل فیلدهای دکمهای (impact_type, subtype)")


def test_button_fields():
    """BUTTON_FIELDS گزینههای معتبر دارد."""
    impact = kai.BUTTON_FIELDS["suggestion"]["impact_type"]
    assert "کیفی" in impact and "کمی" in impact
    subtypes = kai.BUTTON_FIELDS["explicit"]["subtype"]
    assert "کتاب" in subtypes
    assert "مقاله" in subtypes
    ok("BUTTON_FIELDS شامل کیفی/کمی و زیرنوع‌های دانش صریح")


def test_interview_prompt_contains_required_sections():
    p = kiv.build_interview_system_prompt("lesson")
    assert "مصاحبه‌گر" in p or "مصاحبهگر" in p
    assert "lesson" in p.lower() or "درس" in p
    assert "context" in p and "result" in p
    assert "done" in p
    assert "extracted" in p
    ok("build_interview_system_prompt شامل همهٔ بخش‌های ضروری")


def test_polish_prompt_basic():
    p = kiv.build_polish_system_prompt()
    assert "narrative" in p
    assert "hashtags" in p
    assert "extracted_project" in p
    ok("build_polish_system_prompt شامل narrative, hashtags, project")


def test_tree_suggestion_prompt_contains_tree():
    p = kiv.build_tree_suggestion_system_prompt("lesson")
    assert "MAPNA Development" in p  # ریشه درخت
    assert "HSE Management" in p
    assert "suggestions" in p
    assert "confidence" in p
    ok("build_tree_suggestion_system_prompt شامل درخت رسمی")


def test_interview_ai_disabled():
    """اگر AI غیرفعال باشد، interview_next_turn باید error=ai_disabled برگرداند."""
    kai.is_ai_enabled = lambda: False
    try:
        result = asyncio.run(kiv.interview_next_turn("lesson", [], "پاسخ تست"))
        assert result["error"] == "ai_disabled"
        assert result["done"] is False
        assert result["extracted"] is None
        assert result["ask"] is None
    finally:
        kai.is_ai_enabled = lambda: bool(kai.config.KNOWLEDGE_AI_API_KEY and kai.config.KNOWLEDGE_AI_MODEL)
    ok("interview_next_turn با AI غیرفعال → error=ai_disabled")


def test_interview_mocked_extracted():
    """interview_next_turn با موفق (AI فعال و JSON صحیح)."""
    async def fake(messages, **kw):
        return '{"extracted": {"context": "پروژه تست"}, "ask": "مشکل چه بود؟"}'
    kiv.is_ai_enabled = lambda: True
    _orig = kiv._call_llm_messages
    kiv._call_llm_messages = fake
    try:
        result = asyncio.run(kiv.interview_next_turn("lesson", [], "پاسخ اول"))
        assert result["error"] is None
        assert result["done"] is False
        assert result["extracted"] == {"context": "پروژه تست"}
        assert result["ask"] == "مشکل چه بود؟"
    finally:
        kiv.is_ai_enabled = lambda: False
        kiv._call_llm_messages = _orig
    ok("interview_next_turn با JSON صحیح → فیلدها و سؤال بعدی استخراج میشود")


def test_interview_mocked_done():
    """interview_next_turn وقتی AI سیگنال done میدهد."""
    async def fake(messages, **kw):
        return '{"done": true, "fields": {"context": "...", "result": "..."}, "title": "پیشنهاد", "summary": "خلاصه"}'
    kiv.is_ai_enabled = lambda: True
    _orig = kiv._call_llm_messages
    kiv._call_llm_messages = fake
    try:
        result = asyncio.run(kiv.interview_next_turn("lesson", [], "پاسخ آخر"))
        assert result["done"] is True
        assert result["fields"]["context"] == "..."
        assert result["title"] == "پیشنهاد"
        assert result["summary"] == "خلاصه"
    finally:
        kiv.is_ai_enabled = lambda: False
        kiv._call_llm_messages = _orig
    ok("interview_next_turn سیگنال done → fields + title + summary")


def test_interview_mocked_invalid_json_retries():
    """JSON نامعتبر → یکبار retry → اگر همچنان نامعتبر → error=llm_failed."""
    attempts = []

    async def fake(messages, **kw):
        attempts.append(1)
        return "not valid json {"
    kiv.is_ai_enabled = lambda: True
    _orig = kiv._call_llm_messages
    kiv._call_llm_messages = fake
    try:
        result = asyncio.run(kiv.interview_next_turn("lesson", [], "x"))
        assert result["error"] == "llm_failed"
        assert len(attempts) == 2, f"باید۲ بار تلاش کند، اما {len(attempts)} بار کرد"
    finally:
        kiv.is_ai_enabled = lambda: False
        kiv._call_llm_messages = _orig
    ok("interview_next_turn JSON نامعتبر → یکبار retry + error")


def test_polish_ai_disabled():
    kiv.is_ai_enabled = lambda: False
    try:
        result = asyncio.run(kiv.polish_dana_draft("lesson", {"context": "..."}, "شرح تست"))
        assert result["narrative"] is None
        assert result["hashtags"] is None
    finally:
        kiv.is_ai_enabled = lambda: False
    ok("polish_dana_draft با AI غیرفعال → None")


def test_polish_mocked_full():
    """polish_dana_draft با پاسخ کامل."""
    async def fake(messages, **kw):
        return '{"narrative": "narrative فارسی", "extracted_project": "پروژه شیراز", "hashtags": ["a","b","c"], "title_suggestion": "عنوان بهتر"}'
    kiv.is_ai_enabled = lambda: True
    _orig = kiv._call_llm_messages
    kiv._call_llm_messages = fake
    try:
        result = asyncio.run(kiv.polish_dana_draft(
            "lesson", {"context": "..."}, "شرح اولیه شامل نام پروژه شیراز"
        ))
        assert result["narrative"] == "narrative فارسی"
        assert result["extracted_project"] == "پروژه شیراز"
        assert result["hashtags"] == ["a", "b", "c"]
        assert result["title_suggestion"] == "عنوان بهتر"
    finally:
        kiv.is_ai_enabled = lambda: False
        kiv._call_llm_messages = _orig
    ok("polish_dana_draft با JSON کامل → narrative, project, hashtags, title")


def test_polish_hashtags_cleaned():
    """هشتگهای دارای # یا فاصله تمیز میشوند."""
    async def fake(messages, **kw):
        return '{"narrative": null, "extracted_project": null, "extracted_contractor": null, "hashtags": ["  #test  ", "برچسب۲"], "title_suggestion": null}'
    kiv.is_ai_enabled = lambda: True
    _orig = kiv._call_llm_messages
    kiv._call_llm_messages = fake
    try:
        result = asyncio.run(kiv.polish_dana_draft("lesson", {}, ""))
        assert result["hashtags"] == ["test", "برچسب۲"]
    finally:
        kiv.is_ai_enabled = lambda: False
        kiv._call_llm_messages = _orig
    ok("polish_dana_draft: پاکسازی هشتگ‌ها (حذف # و فاصله)")


def test_suggest_tree_ai_disabled():
    kiv.is_ai_enabled = lambda: False
    try:
        result = asyncio.run(kiv.suggest_tree_paths("lesson", {}, ""))
        assert result == []
    finally:
        kiv.is_ai_enabled = lambda: False
    ok("suggest_tree_paths با AI غیرفعال → []")


def test_suggest_tree_mocked_validated():
    """suggest_tree_paths فقط مسیرهای معتبر در درخت را برمیگرداند."""
    async def fake(messages, **kw):
        return json.dumps({
            "suggestions": [
                {"path": ["MAPNA Development", "HSE Management",
                          "Health, Safety and Environment", "Safety"],
                 "confidence": 0.87, "reason": "ایمنی"},
                {"path": ["نود_نامعلوم", "x", "y", "z"], "confidence": 0.5,
                 "reason": "نامعتبر"},
                {"path": ["MAPNA Development", "Execution Management and Supervision",
                          "Civil Works"], "confidence": 0.6, "reason": "اجرا"},
            ]
        })
    kiv.is_ai_enabled = lambda: True
    _orig = kiv._call_llm_messages
    kiv._call_llm_messages = fake
    try:
        result = asyncio.run(kiv.suggest_tree_paths("lesson", {}, "تست"))
        assert len(result) == 2, f"باید فقط۲ مسیر معتبر برگرداند: {result}"
        assert result[0]["confidence"] == 0.87
        assert result[1]["path"][-1] == "Civil Works"
    finally:
        kiv.is_ai_enabled = lambda: False
        kiv._call_llm_messages = _orig
    ok("suggest_tree_paths: مسیرهای نامعتبر فیلتر میشوند")


import json  # برای تست suggest_tree

def main():
    for fn in (
        test_interview_framework_complete,
        test_interview_framework_includes_buttons,
        test_button_fields,
        test_interview_prompt_contains_required_sections,
        test_polish_prompt_basic,
        test_tree_suggestion_prompt_contains_tree,
        test_interview_ai_disabled,
        test_interview_mocked_extracted,
        test_interview_mocked_done,
        test_interview_mocked_invalid_json_retries,
        test_polish_ai_disabled,
        test_polish_mocked_full,
        test_polish_hashtags_cleaned,
        test_suggest_tree_ai_disabled,
        test_suggest_tree_mocked_validated,
    ):
        fn()
    print(f"\nتمام شد: {passed} تست PASS")


if __name__ == "__main__":
    main()