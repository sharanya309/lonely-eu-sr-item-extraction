#!/usr/bin/env python3
"""Self-consistent database totals. ONE key: article = processed PDF (filename) — the only
identifier present in both phases. Scale = (article, folded scale name). Item = item-bearing
row. Distinct counts; re-runs counted once. Writes database_summary_tables.csv next to this
script. Set LONELY_EU_BASE to the folder holding the (non-distributed) input data."""
import csv, os, unicodedata
from openpyxl import load_workbook
csv.field_size_limit(2**30)
BASE = os.environ.get("LONELY_EU_BASE", ".")
OUT  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database_summary_tables.csv")
def bn(x): return os.path.basename(str(x)).strip().lower() if x else ""
def fold(s):
    s=(str(s) if s else "").replace("ı","i").replace("İ","i").replace("ş","s").replace("ğ","g").replace("ç","c").replace("ö","o").replace("ü","u")
    s=unicodedata.normalize("NFKD",s); s="".join(c for c in s if not unicodedata.combining(c))
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in s).split())

# PHASE 1
p1_run=set(f for f in (bn(r.get("filename")) for r in csv.DictReader(open(f"{BASE}/26 May_rerun/merged_all_batches.csv",encoding="utf-8",errors="replace"))) if f)
wb=load_workbook(f"{BASE}/CLAUDE_WORKSPACE/04_reference_copies/step2a_deduplicated_scales.xlsx",read_only=True); ws=wb.active
it=ws.iter_rows(values_only=True); h=list(next(it)); fi=h.index("filename"); sn=h.index("scale_name")
p1_items=set(); p1_scale=set(); p1_itemrows=0
for row in it:
    p1_itemrows+=1                       # every item row counts as an item
    f=bn(row[fi])
    if not f: continue                   # filename only needed for paper/scale attribution
    p1_items.add(f)
    if fold(row[sn]): p1_scale.add((f,fold(row[sn])))
wb.close()
# PHASE 2
p2_run=set(); p2_items=set(); p2_scale=set(); p2_itemrows=0; srow=set(); shas=set()
for r in csv.DictReader(open(f"{BASE}/pipeline_final_v3 final/data/final/master_flat.csv",encoding="utf-8",errors="replace")):
    has_item=bool((r.get("item_text_english") or "").strip() or (r.get("item_text_original") or "").strip())
    if has_item: p2_itemrows+=1        # every item row counts
    f=bn(r.get("filename"))
    if not f: continue                 # filename only needed for paper/scale attribution
    p2_run.add(f)
    sc=(f,fold(r.get("scale_name"))) if fold(r.get("scale_name")) else None
    if sc: srow.add(sc)
    if has_item:
        p2_items.add(f)
        if sc: p2_scale.add(sc); shas.add(sc)

RUN=p1_run|p2_run; ITEMS=p1_items|p2_items; SCALE=p1_scale|p2_scale
rows=[["metric","Phase 1","Phase 2","Combined (distinct)"],
 ["articles run (distinct PDF files)", len(p1_run),          len(p2_run),          len(RUN)],
 ["articles with items",    len(p1_items),        len(p2_items),        len(ITEMS)],
 ["articles run, no items", len(p1_run-p1_items), len(p2_run-p2_items), len(RUN-ITEMS)],
 ["scales with >=1 item",   len(p1_scale),        len(p2_scale),        len(SCALE)],
 ["scales incl. records with no items", len(p1_scale), len(srow), len(p1_scale|srow)],
 ["items",                  p1_itemrows,          p2_itemrows,          p1_itemrows+p2_itemrows]]
with open(OUT,"w",newline="",encoding="utf-8") as f: csv.writer(f).writerows(rows)
for r in rows: print(f"{str(r[0]):<36}{str(r[1]):>9}{str(r[2]):>9}{str(r[3]):>13}")
print(f"\nre-run overlap (Phase-1 ∩ Phase-2): {len(p1_run&p2_run)}   naive sum {len(p1_run)+len(p2_run)} -> distinct {len(RUN)}")
print(f"Phase-2 scales with a record but NO items: {len(srow-shas)}")
print(f"wrote {OUT}")
