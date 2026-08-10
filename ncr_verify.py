import io
import sys

import openpyxl

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

wb = openpyxl.load_workbook(r"media/exports/NCR_sample.xlsx")
ws = wb.active
coords = ["C2", "P2", "P4", "A6", "A7", "F7", "A8", "H5", "J7", "A11", "A9", "A12", "A15", "A16"]
for c in coords:
    print(c, "=>", repr(ws[c].value)[:110])
