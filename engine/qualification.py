"""
engine/qualification.py — ASME Section IX Welder Performance Qualification Engine

بازطراحی کامل مطابق WelderBot_ASME_Spec_v2_4.md (نسخه ۲.۴).
این ماژول Pure Logic است — بدون هیچ وابستگی به Telegram یا دیتابیس.

قرارداد سازگاری با db.models.add_qualification():
    خروجی QualificationEngine.calculate() شامل ۸ کلید ثابت qr_* است که مستقیماً
    در payload آن تابع قرار می‌گیرند (بدون دستکاری):
        qr_process, qr_backing, qr_p_no, qr_thickness, qr_diameter,
        qr_position_groove, qr_position_fillet, qr_f_no
    کلیدهای qr_p_no / qr_position_groove / qr_position_fillet / qr_f_no
    همیشه از نوع list[str] هستند (چون db.models آن‌ها را JSON-serialize می‌کند).
    کلید "extra" در خروجی، برای ذخیره در ستون extra_data (JSON آزاد) در نظر
    گرفته شده و شامل تمام داده‌های تکمیلی است که ستون اختصاصی در دیتابیس ندارند.

هر Rule یا مستقیماً به بند استاندارد ASME BPVC Section IX ارجاع دارد، یا به‌صراحت
با کامنت "Project-Specific Design Decision" علامت‌گذاری شده است — مطابق الزام
صریح خود سند اسپک (بخش «نکته مهم»).
"""

from __future__ import annotations

from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# ثابت‌های واحد و آستانه‌ها
# ══════════════════════════════════════════════════════════════════════════════

# معادل‌های دقیق میلی‌متری اینچ — برای Rule Matrix QW-452.3 / QW-452.4
_IN_1_MM       = 25.4      # 1"
_IN_2_875_MM   = 73.025    # 2⅞"
_IN_24_MM      = 609.6     # 24" — سقف پشتیبانی‌نشده در این نسخه (تصمیم پروژه)

# آستانه ضخامت فلز پایه — QW-452.1(b)
_THICKNESS_THRESHOLD_MM = 13.0
_MIN_PASS_FOR_UNLIMITED = 3

# نشانگرهای موقعیت عمودی — QW-405.3 (برای تشخیص خودکار Progression)
_VERTICAL_POSITION_MARKERS = ("3G", "3F", "5G", "6G")

PROCESS_OPTIONS  = ["SMAW", "GTAW", "GTAW+SMAW"]
SPECIMEN_OPTIONS = ["PLATE", "PIPE"]
JOINT_OPTIONS    = ["GROOVE", "FILLET"]

SUPPORTED_P_NUMBERS = ["P1", "P3", "P5A", "P8", "P15E"]
P_NUMBER_DISPLAY = {
    "P1":   "P-No. 1",
    "P3":   "P-No. 3",
    "P5A":  "P-No. 5A",
    "P8":   "P-No. 8",
    "P15E": "P-No. 15E",
}

# ══════════════════════════════════════════════════════════════════════════════
# Rule Matrix — Position Qualification (QW-461.9)
# منبع: WelderBot_ASME_Spec_v2_4.md — بخش «Rule Matrix – Position Qualification»
# این جدول مستقل از Process است (برای SMAW / GTAW / GTAW+SMAW یکسان اعمال می‌شود).
# ══════════════════════════════════════════════════════════════════════════════

# Plate → Groove
# نکته: ستون "pipe_groove" یک Cross-Qualification اضافه به روی Pipe است (نه جایگزین
# qualified_groove خود Plate). چون db.models فقط یک فیلد qr_position_groove دارد،
# این Cross-Qualification در calculate() جداگانه در extra_data ذخیره می‌شود، نه در
# qr_position_groove اصلی (که فقط qualified_groove خود Plate را نشان می‌دهد).
# ⚠️ این یک تصمیم طراحی من است چون خود سند این بخش را زیر «مواردی که هنوز طراحی
#    نشده‌اند → Final Qualification Output Logic» علامت زده — باید توسط شما تایید شود.
PLATE_GROOVE_POSITIONS = {
    "1G": {
        "groove": ["1G"],
        "pipe_groove": ["1G"],
        "pipe_groove_note": "فقط برای OD > 2⅞″ تا < 24″ معتبر است",
        "fillet": ["1F"],
    },
    "2G": {
        "groove": ["1G", "2G"],
        "pipe_groove": ["1G", "2G"],
        "pipe_groove_note": None,
        "fillet": ["1F", "2F"],
    },
    "3G": {
        "groove": ["1G", "3G"],
        "pipe_groove": ["1G"],
        "pipe_groove_note": None,
        "fillet": ["1F", "2F", "3F"],
    },
    "4G": {
        "groove": ["1G", "4G"],
        "pipe_groove": ["1G"],
        "pipe_groove_note": None,
        "fillet": ["1F", "2F", "4F"],
    },
    "3G+4G": {
        "groove": ["1G", "3G", "4G"],
        "pipe_groove": ["1G"],
        "pipe_groove_note": None,
        "fillet": ["1F", "2F", "3F", "4F"],
    },
    "2G+3G+4G": {
        "groove": ["1G", "2G", "3G", "4G"],
        "pipe_groove": ["1G", "2G"],
        "pipe_groove_note": None,
        "fillet": ["1F", "2F", "3F", "4F"],
    },
}

# Plate → Fillet
PLATE_FILLET_POSITIONS = {
    "1F":    {"fillet": ["1F"]},
    "2F":    {"fillet": ["1F", "2F"]},
    "3F":    {"fillet": ["1F", "2F", "3F"]},
    "4F":    {"fillet": ["1F", "2F", "4F"]},
    "3F+4F": {"fillet": ["1F", "2F", "3F", "4F"]},
}

# Pipe → Groove
# ⚠️ اصلاح‌شده مطابق v2.4: ستون Qualified Fillet برای 5G/6G/2G+5G صحیح شده
# (3F حذف شد چون اصلاً در دامنه Pipe→Fillet تعریف نشده — مقدار صحیح 1F+2F+4F+5F است)
PIPE_GROOVE_POSITIONS = {
    "1G":    {"groove": ["1G"],                "fillet": ["1F"]},
    "2G":    {"groove": ["1G", "2G"],          "fillet": ["1F", "2F"]},
    "5G":    {"groove": ["1G", "2G", "5G"],       "fillet": ["1F", "2F", "4F", "5F"]},
    "6G":    {"groove": ["1G", "2G", "5G", "6G"], "fillet": ["1F", "2F", "4F", "5F"]},
    "2G+5G": {"groove": ["1G", "2G", "5G", "6G"], "fillet": ["1F", "2F", "4F", "5F"]},
}

# Pipe → Fillet
PIPE_FILLET_POSITIONS = {
    "1F": {"fillet": ["1F"]},
    "2F": {"fillet": ["1F", "2F"]},
    "4F": {"fillet": ["1F", "2F", "4F"]},
    "5F": {"fillet": ["1F", "2F", "4F", "5F"]},
}

_POSITION_TABLES = {
    ("PLATE", "GROOVE"): PLATE_GROOVE_POSITIONS,
    ("PLATE", "FILLET"): PLATE_FILLET_POSITIONS,
    ("PIPE",  "GROOVE"): PIPE_GROOVE_POSITIONS,
    ("PIPE",  "FILLET"): PIPE_FILLET_POSITIONS,
}


def get_valid_positions(specimen_type: str, joint_type: str) -> list[str]:
    """
    گزینه‌های قابل‌انتخاب Position برای یک ترکیب Specimen+Joint را برمی‌گرداند.
    ترتیب خروجی همان ترتیب جدول اسپک است (برای ساخت کیبورد).

    خطا:
        ValueError اگر ترکیب specimen_type/joint_type نامعتبر باشد.
    """
    key = (specimen_type, joint_type)
    if key not in _POSITION_TABLES:
        raise ValueError(f"ترکیب نامعتبر Specimen/Joint: {specimen_type}/{joint_type}")
    return list(_POSITION_TABLES[key].keys())


# ══════════════════════════════════════════════════════════════════════════════
# Material Database — QW-423.1
# منبع: WelderBot_ASME_Spec_v2_4.md — بخش «Material Database and P-Number Mapping»
# ══════════════════════════════════════════════════════════════════════════════

PIPE_MATERIALS = [
    {"designation": "SA-106 Gr. B",  "p_no": "P1",   "use": "Carbon steel pipe"},
    {"designation": "SA-53 Gr. B",   "p_no": "P1",   "use": "Carbon steel pipe"},
    {"designation": "SA-335 Gr. P1", "p_no": "P3",   "use": "Low alloy pipe"},
    {"designation": "SA-335 Gr. P22","p_no": "P5A",  "use": "Cr-Mo high temperature pipe"},
    {"designation": "SA-312 TP304",  "p_no": "P8",   "use": "Stainless steel pipe"},
    {"designation": "SA-312 TP316",  "p_no": "P8",   "use": "Stainless steel pipe"},
    {"designation": "SA-335 Gr. P91","p_no": "P15E", "use": "Creep strength enhanced ferritic pipe"},
]

PLATE_MATERIALS = [
    {"designation": "SA-516 Gr. 70", "p_no": "P1",   "use": "Carbon steel pressure vessel plate"},
    {"designation": "SA-36",         "p_no": "P1",   "use": "Carbon steel structural plate"},
    {"designation": "SA-204 Gr. B",  "p_no": "P3",   "use": "Molybdenum alloy pressure vessel plate"},
    {"designation": "SA-387 Gr. 22", "p_no": "P5A",  "use": "Cr-Mo pressure vessel plate"},
    {"designation": "SA-240 Gr. 304","p_no": "P8",   "use": "Stainless steel plate"},
    {"designation": "SA-240 Gr. 316","p_no": "P8",   "use": "Stainless steel plate"},
    {"designation": "SA-387 Gr. 91", "p_no": "P15E", "use": "Creep strength enhanced ferritic plate"},
]


def get_materials(specimen_type: str) -> list[dict]:
    """فهرست متریال‌های از پیش‌تعریف‌شده را بر اساس Specimen Type برمی‌گرداند."""
    return PIPE_MATERIALS if specimen_type == "PIPE" else PLATE_MATERIALS


# ══════════════════════════════════════════════════════════════════════════════
# Filler / Electrode Database — QW-433
# منبع: WelderBot_ASME_Spec_v2_4.md — بخش «Filler / Electrode Selection»
# ══════════════════════════════════════════════════════════════════════════════

SMAW_ELECTRODES = [
    {"designation": "E7018",     "f_no": "F4", "sfa": "SFA-5.1",  "related": "P-No. 1"},
    {"designation": "E8018-B2",  "f_no": "F4", "sfa": "SFA-5.5",  "related": "P-No. 3 / P-No. 5A"},
    {"designation": "E9018-B3",  "f_no": "F4", "sfa": "SFA-5.5",  "related": "P-No. 5A"},
    {"designation": "E308L-16",  "f_no": "F5", "sfa": "SFA-5.4",  "related": "P-No. 8"},
    {"designation": "E316L-16",  "f_no": "F5", "sfa": "SFA-5.4",  "related": "P-No. 8"},
    {"designation": "E9015-B91", "f_no": "F4", "sfa": "SFA-5.5",  "related": "P-No. 15E"},
]

GTAW_FILLERS = [
    {"designation": "ER70S-6",  "f_no": "F6", "sfa": "SFA-5.18", "related": "P-No. 1"},
    {"designation": "ER80S-B2", "f_no": "F6", "sfa": "SFA-5.28", "related": "P-No. 3 / P-No. 5A"},
    {"designation": "ER90S-B3", "f_no": "F6", "sfa": "SFA-5.28", "related": "P-No. 5A"},
    {"designation": "ER308L",   "f_no": "F6", "sfa": "SFA-5.9",  "related": "P-No. 8"},
    {"designation": "ER316L",   "f_no": "F6", "sfa": "SFA-5.9",  "related": "P-No. 8"},
    {"designation": "ER90S-B9", "f_no": "F6", "sfa": "SFA-5.28", "related": "P-No. 15E"},
]


def get_electrodes(process: str) -> list[dict]:
    """SMAW → لیست الکترود، GTAW → لیست فیلر."""
    return SMAW_ELECTRODES if process == "SMAW" else GTAW_FILLERS


# ══════════════════════════════════════════════════════════════════════════════
# استثنای اعتبارسنجی اختصاصی موتور
# ══════════════════════════════════════════════════════════════════════════════

class QualificationValidationError(ValueError):
    """خطای اعتبارسنجی ورودی‌های موتور — پیام قابل‌نمایش مستقیم به اپراتور."""
    pass


# ══════════════════════════════════════════════════════════════════════════════
# QualificationEngine
# ══════════════════════════════════════════════════════════════════════════════

class QualificationEngine:
    """
    موتور محاسبه صلاحیت جوشکار — Pure Logic، بدون state داخلی بین فراخوانی‌ها.
    تنها متد ورودی: calculate(inputs: dict) -> dict
    """

    # ────────────────────────────────────────────────────────────────────
    # QW-461.9 — Position
    # ────────────────────────────────────────────────────────────────────
    def _calc_position(self, specimen_type: str, joint_type: str, test_position: str) -> dict:
        table = _POSITION_TABLES.get((specimen_type, joint_type))
        if table is None:
            raise QualificationValidationError(
                f"ترکیب نامعتبر Specimen/Joint: {specimen_type}/{joint_type}"
            )
        row = table.get(test_position)
        if row is None:
            raise QualificationValidationError(
                f"موقعیت «{test_position}» برای {specimen_type}/{joint_type} معتبر نیست. "
                f"گزینه‌های مجاز: {', '.join(table.keys())}"
            )

        qr_position_groove = list(row.get("groove", []))
        qr_position_fillet = list(row.get("fillet", []))

        detail = {
            "operator_choice": test_position,
            "own_specimen_groove": qr_position_groove,
            "own_specimen_fillet": qr_position_fillet,
        }
        # Cross-Qualification روی Pipe (فقط برای Plate→Groove وجود دارد)
        if "pipe_groove" in row:
            detail["cross_qualified_pipe_groove"] = row["pipe_groove"]
            detail["cross_qualified_pipe_groove_note"] = row.get("pipe_groove_note")

        return {
            "qr_position_groove": qr_position_groove,
            "qr_position_fillet": qr_position_fillet,
            "detail": detail,
        }

    # ────────────────────────────────────────────────────────────────────
    # QW-405.3 — Progression (خودکار، بدون سوال از اپراتور)
    # ────────────────────────────────────────────────────────────────────
    def _calc_progression(self, test_position: str) -> Optional[str]:
        if any(marker in test_position for marker in _VERTICAL_POSITION_MARKERS):
            return "Uphill"
        return None  # موقعیت غیرعمودی — Progression معتبر/الزامی نیست

    # ────────────────────────────────────────────────────────────────────
    # QW-452.3 (Groove) / QW-452.4 (Fillet) — Pipe Diameter
    # ────────────────────────────────────────────────────────────────────
    def _calc_diameter(self, specimen_type: str, joint_type: str, pipe_od_mm: Optional[float]) -> str:
        if specimen_type == "PLATE":
            # Project-Specific Design Decision: قطر برای Plate اساساً موضوعیت ندارد
            return "N/A (Plate specimen)"

        if pipe_od_mm is None:
            raise QualificationValidationError("برای Specimen = Pipe، قطر خارجی (OD) باید وارد شود.")
        if pipe_od_mm <= 0:
            raise QualificationValidationError("قطر خارجی باید عددی مثبت باشد.")
        if pipe_od_mm >= _IN_24_MM:
            raise QualificationValidationError(
                "قطرهای ≥ 24 اینچ (609.6mm) در این نسخه پشتیبانی نمی‌شوند."
            )

        if pipe_od_mm < _IN_1_MM:
            return "Size Welded to Unlimited"
        elif pipe_od_mm <= _IN_2_875_MM:
            return "1″ to Unlimited"
        else:
            return "2⅞″ to Unlimited"

    # ────────────────────────────────────────────────────────────────────
    # QW-452.1(b) — Base Metal Thickness / Deposit Thickness / Pass Count
    # فقط برای Joint Type = Groove (طبق تصریح صریح اسپک — برای Fillet طراحی نشده)
    # ────────────────────────────────────────────────────────────────────
    def _qw452_1b_single(self, thickness_mm: float, pass_count: Optional[int], label: str) -> tuple[str, Optional[float]]:
        """
        محاسبه‌ی مستقل QW-452.1(b) برای یک Process تنها (SMAW-تنها یا GTAW-تنها،
        یا هرکدام از دو Process در حالت GTAW+SMAW).
        خروجی: (متن نمایشی, مقدار عددی ضخامت مجاز یا None اگر Unlimited)
        """
        if thickness_mm is None or thickness_mm <= 0:
            raise QualificationValidationError(f"ضخامت {label} باید عددی مثبت باشد.")

        if thickness_mm < _THICKNESS_THRESHOLD_MM:
            qualified = 2 * thickness_mm
            return f"Up to {qualified:.1f} mm", qualified

        # ضخامت ≥ 13mm → تعداد پاس الزامی است
        if pass_count is None:
            raise QualificationValidationError(
                f"چون ضخامت {label} ≥ 13mm است، تعداد پاس جوش باید وارد شود."
            )
        if pass_count < 1:
            raise QualificationValidationError("تعداد پاس باید عددی مثبت باشد.")

        if pass_count >= _MIN_PASS_FOR_UNLIMITED:
            return "Unlimited", None
        else:
            qualified = 2 * thickness_mm
            return f"Up to {qualified:.1f} mm", qualified

    def _calc_thickness(self, process: str, joint_type: str, inputs: dict) -> dict:
        """
        خروجی:
            {
                "qr_thickness": str  (متن نهایی برای فیلد qr_thickness در DB),
                "detail": {...}      (برای extra_data)
            }
        """
        if joint_type == "FILLET":
            # صراحتاً در اسپک: «این بخش فعلاً فقط برای Groove نهایی شده است»
            return {
                "qr_thickness": "N/A (Fillet — قانون ضخامت هنوز طبق v2.4 طراحی نشده)",
                "detail": {"note": "QW-452.1(b) Fillet not yet designed per spec v2.4"},
            }

        if process in ("SMAW", "GTAW"):
            # حالت ۱ (SMAW تنها) و حالت ۳ (GTAW تنها) — منطق یکسان
            thk = inputs.get("base_metal_thickness_mm")
            passes = inputs.get("pass_count")
            text, qualified_mm = self._qw452_1b_single(thk, passes, "فلز پایه")
            return {
                "qr_thickness": text,
                "detail": {
                    "base_metal_thickness_mm": thk,
                    "pass_count": passes,
                    "qualified_deposit_thickness_mm": qualified_mm,
                    "rule_case": "SMAW-alone" if process == "SMAW" else "GTAW-alone",
                },
            }

        if process == "GTAW+SMAW":
            # حالت ۲ — دو محاسبه‌ی مستقل، بدون سوال «ضخامت فلز پایه»
            gtaw_thk    = inputs.get("gtaw_deposit_thk_mm")
            gtaw_passes = inputs.get("gtaw_pass_count")
            smaw_thk    = inputs.get("smaw_deposit_thk_mm")
            smaw_passes = inputs.get("smaw_pass_count")

            gtaw_text, gtaw_qualified = self._qw452_1b_single(gtaw_thk, gtaw_passes, "رسوب GTAW")
            smaw_text, smaw_qualified = self._qw452_1b_single(smaw_thk, smaw_passes, "رسوب SMAW")

            combined = f"GTAW: {gtaw_text} | SMAW: {smaw_text}"
            return {
                "qr_thickness": combined,
                "detail": {
                    "gtaw_deposit_thk_mm": gtaw_thk,
                    "gtaw_pass_count": gtaw_passes,
                    "gtaw_qualified_thickness_mm": gtaw_qualified,
                    "smaw_deposit_thk_mm": smaw_thk,
                    "smaw_pass_count": smaw_passes,
                    "smaw_qualified_thickness_mm": smaw_qualified,
                    "rule_case": "GTAW+SMAW",
                },
            }

        raise QualificationValidationError(f"Process نامعتبر: {process}")

    # ────────────────────────────────────────────────────────────────────
    # QW-423.1 — Base Metal P-Number & Qualified Range
    # ────────────────────────────────────────────────────────────────────
    def _calc_p_no(self, base_metal_p_no: str, is_manual_entry: bool = False) -> list[str]:
        """
        خروجی: qr_p_no به‌صورت list (سازگار با db.models).

        Project-Specific Design Decision (طبق اسپک، بخش «Qualified Base Metal Range»):
            اگر P-Number ورودی یکی از ۵ مورد پشتیبانی‌شده باشد (P1/P3/P5A/P8/P15E)،
            محدوده مجاز طبق قانون پروژه: «P-No. 1 through P-No. 15F».
            برای هر P-Number دیگری (فقط از طریق ورود دستی ممکن است رخ دهد)، من محدوده
            را حدس نمی‌زنم — چون سند صراحتاً می‌گوید هیچ Rule نباید صرفاً از حافظه
            پیاده‌سازی شود و QW-423.1 کامل در این نسخه مستند/تایید نشده است.
        """
        if base_metal_p_no in SUPPORTED_P_NUMBERS:
            return ["P-No. 1 through P-No. 15F"]
        return [
            f"نامشخص — {base_metal_p_no} خارج از دامنه پشتیبانی‌شده پروژه است؛ "
            f"محدوده مجاز باید دستی و مطابق QW-423.1 کامل تایید شود."
        ]

    # ────────────────────────────────────────────────────────────────────
    # QW-433 — Filler / Electrode F-Number
    # ────────────────────────────────────────────────────────────────────
    def _calc_f_no(self, process: str, filler_smaw: Optional[dict], filler_gtaw: Optional[dict]) -> dict:
        """
        filler_smaw / filler_gtaw هرکدام دیکشنری {"designation","f_no","sfa"} است
        (یا None اگر آن Process فعال نیست).

        خروجی:
            {"qr_f_no": list[str] یکتا، "filler_f_no_display": str, "detail": {...}}
        """
        f_numbers: list[str] = []
        detail: dict = {}

        if process in ("SMAW", "GTAW+SMAW"):
            if not filler_smaw or not filler_smaw.get("f_no"):
                raise QualificationValidationError("الکترود SMAW انتخاب/وارد نشده است.")
            f_numbers.append(filler_smaw["f_no"])
            detail["smaw_electrode"] = filler_smaw

        if process in ("GTAW", "GTAW+SMAW"):
            if not filler_gtaw or not filler_gtaw.get("f_no"):
                raise QualificationValidationError("فیلر GTAW انتخاب/وارد نشده است.")
            f_numbers.append(filler_gtaw["f_no"])
            detail["gtaw_filler"] = filler_gtaw

        # حذف تکراری با حفظ ترتیب
        seen = set()
        unique_f_numbers = [f for f in f_numbers if not (f in seen or seen.add(f))]

        if process == "GTAW+SMAW":
            display = f"GTAW: {filler_gtaw['designation']} (F{filler_gtaw['f_no'].lstrip('F')}) / " \
                      f"SMAW: {filler_smaw['designation']} (F{filler_smaw['f_no'].lstrip('F')})"
        elif process == "SMAW":
            display = f"{filler_smaw['designation']} ({filler_smaw['f_no']})"
        else:
            display = f"{filler_gtaw['designation']} ({filler_gtaw['f_no']})"

        return {"qr_f_no": unique_f_numbers, "filler_f_no_display": display, "detail": detail}

    # ────────────────────────────────────────────────────────────────────
    # QW-408 — Gas Variables
    # ────────────────────────────────────────────────────────────────────
    def _calc_gas(self, process: str, joint_type: str, base_metal_p_no: str,
                  shielding_gas_choice: Optional[str]) -> dict:
        result = {"shielding_gas": None, "backing_gas_warning": False, "backing_gas_note": None}

        if "GTAW" in process:
            result["shielding_gas"] = shielding_gas_choice or "Argon 99.9%"

        if joint_type == "GROOVE" and base_metal_p_no in ("P8", "P15E"):
            result["backing_gas_warning"] = True
            result["backing_gas_note"] = (
                "⚠️ برای اتصالات Groove در متریال P-No. 8 / P-No. 15E، "
                "استفاده از گاز پشت‌بند Argon 99% الزامی است."
            )
            result["backing_gas_qualified"] = "Argon 99% backing gas"

        return result

    # ────────────────────────────────────────────────────────────────────
    # QW-409.4 — Electrical Characteristics
    # ────────────────────────────────────────────────────────────────────
    def _calc_electrical(self, process: str, elec_smaw: Optional[dict], elec_gtaw: Optional[dict]) -> dict:
        """
        elec_smaw / elec_gtaw: {"current": "AC"|"DC", "polarity": "DCEP"|"DCEN"|None} یا None

        قانون پروژه: Qualified Current/Polarity = دقیقاً همان مقدار تست‌شده (بدون توسعه).
        """
        def _fmt(e: dict, label: str) -> str:
            if not e or not e.get("current"):
                raise QualificationValidationError(f"مشخصات الکتریکی {label} وارد نشده است.")
            if e["current"] == "AC":
                return "AC"
            if not e.get("polarity"):
                raise QualificationValidationError(f"برای جریان DC در {label}، قطبیت باید مشخص شود.")
            return f"DC / {e['polarity']}"

        detail = {}
        if process in ("SMAW", "GTAW+SMAW"):
            detail["smaw"] = _fmt(elec_smaw, "SMAW")
        if process in ("GTAW", "GTAW+SMAW"):
            detail["gtaw"] = _fmt(elec_gtaw, "GTAW")
        return detail

    # ────────────────────────────────────────────────────────────────────
    # متد اصلی
    # ────────────────────────────────────────────────────────────────────
    def calculate(self, inputs: dict) -> dict:
        """
        ورودی inputs — کلیدهای مورد انتظار (بسته به مسیر، برخی اختیاری‌اند):

            process, specimen_type, joint_type, test_position,
            pipe_od_mm,
            base_metal_p_no, base_metal_is_manual,
            base_metal_thickness_mm, pass_count,                       # SMAW/GTAW تنها
            gtaw_deposit_thk_mm, gtaw_pass_count,                      # GTAW+SMAW
            smaw_deposit_thk_mm, smaw_pass_count,                      # GTAW+SMAW
            filler_smaw, filler_gtaw,                                  # dict یا None
            shielding_gas,
            elec_smaw, elec_gtaw,                                      # dict یا None

        خروجی:
            {
                "qr_process": str,
                "qr_backing": str,
                "qr_p_no": list[str],
                "qr_thickness": str,
                "qr_diameter": str,
                "qr_position_groove": list[str],
                "qr_position_fillet": list[str],
                "qr_f_no": list[str],
                "filler_f_no_display": str,   # برای فیلد raw «filler_f_no» (نه qr_)
                "progression": str | None,
                "extra": {...}                # برای ستون extra_data
            }

        خطا:
            QualificationValidationError با پیام قابل‌نمایش مستقیم به اپراتور.
        """
        process       = inputs.get("process")
        specimen_type = inputs.get("specimen_type")
        joint_type    = inputs.get("joint_type")
        test_position = inputs.get("test_position")
        base_metal_p_no = inputs.get("base_metal_p_no")

        if process not in PROCESS_OPTIONS:
            raise QualificationValidationError(f"Process نامعتبر: {process}")
        if specimen_type not in SPECIMEN_OPTIONS:
            raise QualificationValidationError(f"Specimen Type نامعتبر: {specimen_type}")
        if joint_type not in JOINT_OPTIONS:
            raise QualificationValidationError(f"Joint Type نامعتبر: {joint_type}")
        if not base_metal_p_no:
            raise QualificationValidationError("P-Number متریال فلز پایه مشخص نشده است.")

        # ── Position (QW-461.9) ──────────────────────────────────────────
        pos_result = self._calc_position(specimen_type, joint_type, test_position)

        # ── Diameter (QW-452.3 / QW-452.4) ───────────────────────────────
        qr_diameter = self._calc_diameter(specimen_type, joint_type, inputs.get("pipe_od_mm"))

        # ── Thickness (QW-452.1(b)) ──────────────────────────────────────
        thickness_result = self._calc_thickness(process, joint_type, inputs)

        # ── P-Number (QW-423.1) ──────────────────────────────────────────
        qr_p_no = self._calc_p_no(base_metal_p_no, inputs.get("base_metal_is_manual", False))

        # ── Filler / Electrode (QW-433) ──────────────────────────────────
        f_no_result = self._calc_f_no(process, inputs.get("filler_smaw"), inputs.get("filler_gtaw"))

        # ── Progression (QW-405.3) ───────────────────────────────────────
        progression = self._calc_progression(test_position)
        # طبق QW-405.3: تأیید با Uphill هم Uphill هم Downhill را پوشش می‌دهد؛
        # این engine هرگز Downhill را برنمی‌گرداند، پس رنج تأیید همیشه یکی از این دو حالت است.
        qr_progression = "Uphill & Downhill" if progression == "Uphill" else None

        # طبق QW-405.3:
        # تأیید با Uphill هر دو حالت Uphill و Downhill را پوشش می‌دهد.
        qr_progression = "Uphill & Downhill" if progression == "Uphill" else None

        # ── Gas (QW-408) ──────────────────────────────────────────────────
        gas_result = self._calc_gas(process, joint_type, base_metal_p_no, inputs.get("shielding_gas"))

        # ── Electrical (QW-409.4) ────────────────────────────────────────
        electrical_result = self._calc_electrical(
            process, inputs.get("elec_smaw"), inputs.get("elec_gtaw")
        )

        # ── Backing (تصمیم پروژه: سوال حذف شده، خروجی همیشه ثابت) ────────
        qr_backing = "Qualified for With Backing and Without Backing"

        return {
            "qr_process":         process,
            "qr_backing":         qr_backing,
            "qr_p_no":            qr_p_no,
            "qr_thickness":       thickness_result["qr_thickness"],
            "qr_diameter":        qr_diameter,
            "qr_position_groove": pos_result["qr_position_groove"],
            "qr_position_fillet": pos_result["qr_position_fillet"],
            "qr_f_no":            f_no_result["qr_f_no"],
            "filler_f_no_display": f_no_result["filler_f_no_display"],
            "progression":        progression,
            "extra": {
                "position_detail":   pos_result["detail"],
                "thickness_detail":  thickness_result["detail"],
                "filler_detail":     f_no_result["detail"],
                "gas":               gas_result,
                "electrical":        electrical_result,
                "progression":       progression,
                "qr_progression":    qr_progression,
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# تست یکپارچه دستی (اجرا: python -m engine.qualification)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    engine = QualificationEngine()

    print("=" * 70)
    print("تست ۱: SMAW تنها، Plate، Groove، 3G، ضخامت 10mm (< 13)")
    print("=" * 70)
    r1 = engine.calculate({
        "process": "SMAW", "specimen_type": "PLATE", "joint_type": "GROOVE",
        "test_position": "3G", "base_metal_p_no": "P1",
        "base_metal_thickness_mm": 10.0,
        "filler_smaw": {"designation": "E7018", "f_no": "F4", "sfa": "SFA-5.1"},
        "elec_smaw": {"current": "DC", "polarity": "DCEP"},
    })
    for k, v in r1.items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 70)
    print("تست ۲: GTAW+SMAW، Pipe، Groove، 6G، OD=114mm، هر دو ضخامت >=13 با پاس متفاوت")
    print("=" * 70)
    r2 = engine.calculate({
        "process": "GTAW+SMAW", "specimen_type": "PIPE", "joint_type": "GROOVE",
        "test_position": "6G", "pipe_od_mm": 114.0, "base_metal_p_no": "P8",
        "gtaw_deposit_thk_mm": 14.0, "gtaw_pass_count": 4,
        "smaw_deposit_thk_mm": 15.0, "smaw_pass_count": 2,
        "filler_gtaw": {"designation": "ER308L", "f_no": "F6", "sfa": "SFA-5.9"},
        "filler_smaw": {"designation": "E308L-16", "f_no": "F5", "sfa": "SFA-5.4"},
        "elec_gtaw": {"current": "DC", "polarity": "DCEN"},
        "elec_smaw": {"current": "DC", "polarity": "DCEP"},
        "shielding_gas": None,
    })
    for k, v in r2.items():
        print(f"  {k}: {v}")
    assert r2["extra"]["gas"]["backing_gas_warning"] is True, "باید هشدار گاز پشت‌بند برای P8/Groove فعال شود"

    print("\n" + "=" * 70)
    print("تست ۳: Pipe→Fillet، 5F")
    print("=" * 70)
    r3 = engine.calculate({
        "process": "GTAW", "specimen_type": "PIPE", "joint_type": "FILLET",
        "test_position": "5F", "pipe_od_mm": 60.0, "base_metal_p_no": "P1",
        "filler_gtaw": {"designation": "ER70S-6", "f_no": "F6", "sfa": "SFA-5.18"},
        "elec_gtaw": {"current": "AC"},
    })
    for k, v in r3.items():
        print(f"  {k}: {v}")
    assert r3["qr_position_fillet"] == ["1F", "2F", "4F", "5F"]
    # توجه: 5F در فهرست نشانگرهای عمودی اسپک (3G/3F/5G/6G) نیست → Progression ثبت نمی‌شود
    assert r3["progression"] is None

    print("\n" + "=" * 70)
    print("تست ۴: خطای اعتبارسنجی — OD >= 24 اینچ")
    print("=" * 70)
    try:
        engine.calculate({
            "process": "SMAW", "specimen_type": "PIPE", "joint_type": "GROOVE",
            "test_position": "1G", "pipe_od_mm": 700.0, "base_metal_p_no": "P1",
            "base_metal_thickness_mm": 10.0,
            "filler_smaw": {"designation": "E7018", "f_no": "F4", "sfa": "SFA-5.1"},
            "elec_smaw": {"current": "AC"},
        })
        print("  ❌ خطا انتظار می‌رفت ولی رخ نداد!")
    except QualificationValidationError as e:
        print(f"  ✅ خطای مورد انتظار: {e}")

    print("\n" + "=" * 70)
    print("✅ تمام تست‌ها اجرا شدند.")
    print("=" * 70)
