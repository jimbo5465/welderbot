
"""پکیج engine — موتور محاسبه دامنه صلاحیت ASME Section IX.



نسخه ۲.۴ — نام‌های زیر برای سازگاری با کد قدیمی نگه داشته شده‌اند (Alias)،

چون qualification.py با ساختار جدید Rule Matrix بازنویسی شده و دیگر این

نام‌های دقیق را ندارد.

"""



from engine.qualification import (

    QualificationEngine,

    QualificationValidationError,

    P_NUMBER_DISPLAY,

    SUPPORTED_P_NUMBERS,

    PLATE_GROOVE_POSITIONS,

    PLATE_FILLET_POSITIONS,

    PIPE_GROOVE_POSITIONS,

    PIPE_FILLET_POSITIONS,

    SMAW_ELECTRODES,

    GTAW_FILLERS,

    get_valid_positions,

    get_materials,

)



# ── Aliasهای سازگاری با نام‌های نسخه قبلی (Deprecated) ──────────────────────

P_NUMBER_RANGE = P_NUMBER_DISPLAY

F_NUMBER_RANGE = {e["f_no"]: e for e in (SMAW_ELECTRODES + GTAW_FILLERS)}

PLATE_POSITION_RANGE = {**PLATE_GROOVE_POSITIONS, **PLATE_FILLET_POSITIONS}

PIPE_POSITION_RANGE = {**PIPE_GROOVE_POSITIONS, **PIPE_FILLET_POSITIONS}



__all__ = [

    "QualificationEngine",

    "QualificationValidationError",

    "P_NUMBER_RANGE",

    "F_NUMBER_RANGE",

    "PLATE_POSITION_RANGE",

    "PIPE_POSITION_RANGE",

    "get_valid_positions",

    "get_materials",

]

