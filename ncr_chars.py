import io
import sys

import openpyxl

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

wb = openpyxl.load_workbook(r"media/templates/NCR.xlsx")
ws = wb.active
for coord in ["H5", "J7", "A11", "A5"]:
    text = ws[coord].value or ""
    print(coord, repr(text)[:200])
    # چاپ کد هر کاراکتر غیرعادی
    odd = [(ch, hex(ord(ch))) for ch in text if ord(ch) > 300 or ch in "5"]
    print("   odd chars:", odd[:20])