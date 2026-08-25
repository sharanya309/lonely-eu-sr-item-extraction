#!/usr/bin/env python3
"""
STEP 2 — build the Item-Coding list: the NEW (de-duplicated) items, with EXACTLY the
six columns required for coding.

Reads : output/01_new_items.csv
Writes: output/items_for_coding.csv  and  .xlsx
        columns: title, country_study, scale_name, subscale, item_text_original, item_text_english
"""
import csv, os, sys
from openpyxl import Workbook
sys.path.insert(0, os.path.dirname(__file__))
from common_paths import OUT
csv.field_size_limit(2**30)

COLS = ["title", "country_study", "scale_name", "subscale",
        "item_text_original", "item_text_english"]

rows = list(csv.DictReader(open(os.path.join(OUT, "01_new_items.csv"), encoding="utf-8")))
out = [{c: r.get(c, "") for c in COLS} for r in rows]

with open(os.path.join(OUT, "items_for_coding.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(out)
wb = Workbook(); ws = wb.active; ws.title = "items_for_coding"; ws.append(COLS)
for r in out: ws.append([r[c] for c in COLS])
ws.freeze_panes = "A2"; wb.save(os.path.join(OUT, "items_for_coding.xlsx"))

print(f"items_for_coding: {len(out)} rows x {len(COLS)} cols")
print("-> output/items_for_coding.csv , output/items_for_coding.xlsx")
