#!/usr/bin/env python3
"""
STEP 3 — RUN AFTER ITEM CODING. Re-map RSF domains back onto EVERY Phase-2 master_flat
item, so nothing is left uncoded.

For each master_flat item row (from item_disposition.csv):
  - disposition == new           -> take final_coding from the CODING OUTPUT (matched on item text)
  - disposition == already_coded -> use inherit_final_coding (from the Phase-1 32,444)
  - disposition == internal_dup  -> use the final_coding of its kept twin (maps_to_row_id)

Usage:
  python3 03_remap_rsf_after_coding.py --coded <coding_output.csv|.xlsx> [--text-col item_text_english] [--code-col final_coding]

The coding-output file must contain the coded NEW items with an item-text column and a
final domain column. Writes output/master_flat_with_rsf.csv (every item row + final_coding)
and reports how many rows were successfully assigned.
"""
import csv, os, sys, argparse
sys.path.insert(0, os.path.dirname(__file__))
from common_paths import MASTER_FLAT, OUT, norm, item_key
csv.field_size_limit(2**30)

ap = argparse.ArgumentParser()
ap.add_argument("--coded", required=True, help="coding-output file (new items + assigned domain)")
ap.add_argument("--text-col", default="item_text_english")
ap.add_argument("--code-col", default="final_coding")
ap.add_argument("--phase1", default=None,
                help="Phase-1 (Feb) coded file (Item + final_coding). Optional fallback for a blank "
                     "NEW item that is really an already-coded Phase-1 item whose exact key differed "
                     "(e.g. an OCR space: 'to tell' vs 'totell'). Every assigned code is a real coded "
                     "value; nothing is invented.")
a = ap.parse_args()

import re
def mnorm(s):
    """Robust match key on top of common_paths.norm(). Item Coding was saved in Excel, which
    writes in-cell line breaks as the literal escape _x000D_ (carriage return) / _x000A_; some
    items are also wrapped in surrounding quotes. norm() alone (whitespace-collapse) leaves those,
    so a coded item like 'We think the people in_x000D_are fair...' never matched the master_flat
    'We think the people in\\nare fair...'. Here we strip the _xHHHH_ escapes, unify smart quotes/
    dashes, run norm(), then strip surrounding quotes/punctuation. No content is altered."""
    s = re.sub(r"_x[0-9A-Fa-f]{4}_", " ", str(s) if s is not None else "")
    for x, y in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-")):
        s = s.replace(x, y)
    return norm(s).strip(" .:;,-\"'()[]")

def aggr(s):
    """Tier-2 key: alphanumeric-only (drops spaces/punctuation). Absorbs internal OCR artifacts
    such as 'to tell' vs 'totell'. Used ONLY as a fallback after the exact mnorm() tier."""
    return re.sub(r"[^a-z0-9]", "", mnorm(s))

def load_any(path):
    if path.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True); ws = wb.active
        h = [c.value for c in next(ws.iter_rows(max_row=1))]
        for row in ws.iter_rows(min_row=2, values_only=True):
            yield dict(zip(h, row))
        wb.close()
    else:
        yield from csv.DictReader(open(path, encoding="utf-8", errors="replace"))

# Build two-tier lookup maps (tier-1 mnorm, tier-2 aggr) from a coded file. First value wins.
def build_maps(path, text_col, code_col):
    m1, m2 = {}, {}
    for r in load_any(path):
        code = r.get(code_col)
        if not code: continue
        it = r.get(text_col)
        k1 = mnorm(it); k2 = aggr(it)
        if k1: m1.setdefault(k1, code)
        if k2: m2.setdefault(k2, code)
    return m1, m2
# Phase-2 September coding output (the run that coded the 45k NEW items).
new1, new2 = build_maps(a.coded, a.text_col, a.code_col)
print(f"coded new-item domains loaded: {len(new1)} (tier-1) / {len(new2)} (tier-2)")
# Phase-1 (Feb) coded set — optional fallback (see --phase1).
feb1, feb2 = build_maps(a.phase1, "Item", "final_coding") if a.phase1 else ({}, {})
if a.phase1: print(f"phase-1 fallback domains loaded: {len(feb1)} (tier-1) / {len(feb2)} (tier-2)")

# master_flat rows by _mid
mf = {}
for i, r in enumerate(csv.DictReader(open(MASTER_FLAT, encoding="utf-8", errors="replace"))):
    if item_key(r.get("item_text_english"), r.get("item_text_original")):
        r["_mid"] = str(i); mf[str(i)] = r

disp = {d["row_id"]: d for d in csv.DictReader(open(os.path.join(OUT, "item_disposition.csv"), encoding="utf-8"))}

def match_coded(mid):
    """Assign a domain by matching the item text against the coded sets. Phase-2 (September) coding
    was done on the ORIGINAL item text, so we match the September set on the ORIGINAL wording FIRST,
    then English; tier-1 (mnorm) then tier-2 (aggr, alphanumeric). If still unresolved, fall back to
    the Phase-1 (Feb) coded set — which was coded on the ENGLISH translation, so there the English
    key is what resolves it. Trying original-then-English on both covers either phase. Every returned
    code is a real coded value; nothing is invented."""
    r = mf.get(mid)
    if not r: return ""
    o, e = r.get("item_text_original"), r.get("item_text_english")
    return (new1.get(mnorm(o)) or new1.get(mnorm(e))          # Sept tier-1: original, then English
            or new2.get(aggr(o)) or new2.get(aggr(e))         # Sept tier-2 (alphanumeric)
            or feb1.get(mnorm(o)) or feb1.get(mnorm(e))       # Phase-1 fallback tier-1
            or feb2.get(aggr(o)) or feb2.get(aggr(e)) or "")  # Phase-1 fallback tier-2

def domain_for(mid):
    d = disp.get(mid)
    if not d: return ""
    if d["disposition"] == "already_coded" and d["inherit_final_coding"]:
        return d["inherit_final_coding"]                      # Phase-1 code captured at dedup time
    if d["disposition"] == "internal_dup":
        v = domain_for(d["maps_to_row_id"])
        if v: return v                                        # inherit the kept twin's code
    # new item, OR an already_coded/internal_dup the disposition left WITHOUT a code (e.g. 01_dedup
    # matched the item to Phase-1 but captured a blank domain): match the coded sets directly.
    return match_coded(mid)

out_rows, assigned = [], 0
for mid, r in mf.items():
    dom = domain_for(mid)
    if dom: assigned += 1
    rr = dict(r); rr["final_coding"] = dom; out_rows.append(rr)

cols = [c for c in out_rows[0].keys() if c != "_mid"] + ["final_coding"]
with open(os.path.join(OUT, "master_flat_with_rsf.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(out_rows)
print(f"item rows total: {len(out_rows)} | assigned an RSF domain: {assigned} | still blank: {len(out_rows)-assigned}")
print("-> output/master_flat_with_rsf.csv")
