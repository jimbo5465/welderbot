"""
تست ماژول knowledge_tree — navigation + validation + rendering.
اجرا: python test_knowledge_tree.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.knowledge_tree import (
    KNOWLEDGE_TREE,
    get_children,
    is_leaf,
    get_leaf_paths,
    find_path_by_leaf_name,
    render_path,
    all_paths_as_lines,
    tree_as_yaml,
    validate_path,
    total_leaf_count,
    total_node_count,
)

passed = 0


def ok(name: str):
    global passed
    passed += 1
    print(f"✅ {name}")


def test_root_level():
    roots = get_children([])
    assert "MAPNA Development" in roots
    assert len(roots) == 1, f"باید فقط ۱ ریشه باشد: {roots}"
    ok("سطح ریشه: فقط MAPNA Development")


def test_second_level():
    children = get_children(["MAPNA Development"])
    assert "HSE Management" in children
    assert "Design and Engineering" in children
    assert len(children) >= 10
    ok("سطح۲: حداقل۱۰ نود از جمله HSE و Design")


def test_is_leaf():
    assert is_leaf(["MAPNA Development", "HSE Management", "Health, Safety and Environment",
                    "Safety"]) is True
    assert is_leaf(["MAPNA Development", "HSE Management"]) is False
    assert is_leaf([]) is False
    ok("is_leaf: تشخیص صحیح برگ و غیربرگ")


def test_find_path_by_leaf_name():
    p = find_path_by_leaf_name("Safety")
    assert p is not None
    assert p[0] == "MAPNA Development"
    assert "HSE Management" in p
    ok(f"find_path_by_leaf_name('Safety') → {p}")


def test_find_path_unknown():
    assert find_path_by_leaf_name("نود_نامعلوم") is None
    ok("find_path_by_leaf_name: نود نامعلوم → None")


def test_render_path():
    assert render_path(["A", "B", "C"]) == "A > B > C"
    assert render_path(["فقط"]) == "فقط"
    ok("render_path: جداسازی با ' > '")


def test_validate_path():
    assert validate_path(["MAPNA Development", "HSE Management"]) is True
    assert validate_path(["MAPNA Development", "Made Up Node"]) is False
    assert validate_path([]) is True  # ریشه معتبر است
    ok("validate_path: مسیر معتبر و نامعتبر")


def test_counts():
    leaves = total_leaf_count()
    nodes = total_node_count()
    assert leaves >= 100, f"تعداد برگ کم است: {leaves}"
    assert nodes > leaves, f"تعداد نود کل کم است: {nodes}"
    print(f"   ↪ total leaves: {leaves}, total nodes: {nodes}")
    ok("total_leaf_count + total_node_count معقول")


def test_all_paths_as_lines():
    lines = all_paths_as_lines()
    assert len(lines) == total_leaf_count()
    assert all(" > " in line for line in lines)
    ok("all_paths_as_lines: همهٔ مسیرها با ' > '")


def test_tree_as_yaml():
    y = tree_as_yaml()
    assert "- MAPNA Development" in y
    assert "  - HSE Management" in y  # تورفتگی۲ فاصله
    assert "    - Safety" in y  # تورفتگی۴ فاصله (سطح۳)
    ok("tree_as_yaml: ساختار تورفتگی صحیح")


def test_knowledge_type_relevant_paths_exist():
    """بررسی که مسیرهای مرتبط با انواع دانش در درخت وجود دارند."""
    all_leaves = set(p[-1] for p in get_leaf_paths())
    # پیشنهاد/تجربه عملی → Execution
    assert "General Execution" in all_leaves
    # ایمنی → HSE
    assert "Safety" in all_leaves
    # کیفیت → QA
    assert "Audits" in all_leaves
    ok("مسیرهای کلیدی (Execution/Safety/QA) در درخت موجود")


def main():
    for fn in (
        test_root_level,
        test_second_level,
        test_is_leaf,
        test_find_path_by_leaf_name,
        test_find_path_unknown,
        test_render_path,
        test_validate_path,
        test_counts,
        test_all_paths_as_lines,
        test_tree_as_yaml,
        test_knowledge_type_relevant_paths_exist,
    ):
        fn()
    print(f"\nتمام شد: {passed} تست PASS")


if __name__ == "__main__":
    main()