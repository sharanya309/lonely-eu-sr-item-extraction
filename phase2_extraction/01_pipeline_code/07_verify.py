#!/usr/bin/env python3
"""
STEP 07 (optional, local, free) — independent integrity audit of the export.

    python3 07_verify.py

Recomputes, straight from the per-paper JSON records (the source of truth),
what master_flat.csv SHOULD contain — without reusing 04_export's own code
path — and diffs that against what's actually in the CSV. Catches:

  * a paper in the corpus (papers_log.csv status=ok) missing a coder
    extraction, a final record, or a master_flat row entirely
  * a master_flat paper_id with no corresponding final record (orphan)
  * a paper's row/item count in master_flat not matching its record
    (would mean 04_export itself dropped or altered something)
  * a paper existing in BOTH data/final/auto/ and data/final/adjudicated/
    (the judge's answer should always be the only one that survives)
  * a genuine duplicate item within one scale object (same item emitted
    twice by a coder/judge and not deduped — inflates item counts)

Exits 0 with a clean report if nothing is wrong, exits 1 and prints every
offending paper_id otherwise. Run this any time you want a defensible answer
to "does master_flat.csv actually reflect every article, exactly once, with
nothing silently dropped or duplicated."
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import resolve
from common import CODERS, FINAL, LOG, banner

RECORDS = FINAL / "records"


def rj(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def expected_rows_for(doc):
    """Re-derive, from the record alone, how many master_flat rows this paper
    SHOULD produce and how many should carry item text — mirrors
    04_export.build_flat's row-emission rule without importing its code, so a
    bug in that code would still be caught here."""
    scales = doc.get("scales") or []
    if not scales:
        return 1, 0
    rows = items_with_text = 0
    for sc in scales:
        items = sc.get("items") or []
        if not items:
            rows += 1
        else:
            rows += len(items)
            for it in items:
                t = (it.get("item_text_original") or it.get("item_text_english") or "").strip()
                if t:
                    items_with_text += 1
    return rows, items_with_text


def main():
    banner("07_verify — independent reconciliation")
    problems = {}

    log_rows = list(csv.DictReader(open(LOG, encoding="utf-8")))
    ok_pids = {r["paper_id"] for r in log_rows if r["status"] == "ok"}

    gem_pids = {p.stem for p in (CODERS / "gemini" / "results").glob("*.json")}
    oai_pids = {p.stem for p in (CODERS / "openai" / "results").glob("*.json")}
    if ok_pids - gem_pids:
        problems["ok_paper_missing_gemini_extraction"] = sorted(ok_pids - gem_pids)
    if ok_pids - oai_pids:
        problems["ok_paper_missing_openai_extraction"] = sorted(ok_pids - oai_pids)

    record_files = list(RECORDS.glob("*.json"))
    record_pids = {p.stem for p in record_files}
    if ok_pids - record_pids:
        problems["ok_paper_missing_final_record"] = sorted(ok_pids - record_pids)
    if record_pids - ok_pids:
        problems["final_record_for_non_ok_paper"] = sorted(record_pids - ok_pids)

    docs = {}
    for p in record_files:
        d = rj(p)
        if d is None:
            problems.setdefault("unreadable_record_json", []).append(p.stem)
        else:
            docs[p.stem] = d

    auto_pids = {p.stem for p in (FINAL / "auto").glob("*.json")} if (FINAL / "auto").exists() else set()
    adj_pids = {p.stem for p in (FINAL / "adjudicated").glob("*.json")} if (FINAL / "adjudicated").exists() else set()
    overlap = auto_pids & adj_pids
    if overlap:
        problems["auto_and_adjudicated_overlap"] = sorted(overlap)

    dup_total, dup_detail = 0, []
    per_paper_expected = {}
    for pid, d in docs.items():
        per_paper_expected[pid] = expected_rows_for(d)
        for sc in d.get("scales") or []:
            items = sc.get("items") or []
            c = defaultdict(int)
            for it in items:
                k = resolve.item_key(it)
                if k:
                    c[k] += 1
            extra = sum(v - 1 for v in c.values() if v > 1)
            if extra:
                dup_total += extra
                dup_detail.append((pid, sc.get("scale_name"), extra))
    if dup_total:
        problems["true_duplicate_items_within_scale"] = dup_detail

    mf_path = FINAL / "master_flat.csv"
    if not mf_path.exists():
        sys.exit("FATAL: data/final/master_flat.csv missing — run 04_export.py first.")
    mf_rows = list(csv.DictReader(open(mf_path, encoding="utf-8")))
    by_pid_rows = defaultdict(list)
    for r in mf_rows:
        by_pid_rows[r["paper_id"]].append(r)
    mf_pids = set(by_pid_rows)
    if record_pids - mf_pids:
        problems["record_missing_from_master_flat"] = sorted(record_pids - mf_pids)
    if mf_pids - record_pids:
        problems["master_flat_paper_not_in_records"] = sorted(mf_pids - record_pids)

    mismatch_rows, mismatch_items = [], []
    for pid, (exp_rows, exp_items) in per_paper_expected.items():
        actual = by_pid_rows.get(pid, [])
        if len(actual) != exp_rows:
            mismatch_rows.append((pid, exp_rows, len(actual)))
            continue
        actual_items = sum(1 for r in actual if (r.get("item_text_original") or "").strip())
        if actual_items != exp_items:
            mismatch_items.append((pid, exp_items, actual_items))
    if mismatch_rows:
        problems["row_count_mismatch(pid,expected,actual)"] = mismatch_rows
    if mismatch_items:
        problems["item_count_mismatch(pid,expected,actual)"] = mismatch_items

    print(f"  corpus (status=ok)      : {len(ok_pids)}")
    print(f"  final records           : {len(record_pids)}")
    print(f"  master_flat paper_ids   : {len(mf_pids)}")
    print(f"  master_flat rows        : {len(mf_rows)}")
    print(f"  auto / adjudicated      : {len(auto_pids)} / {len(adj_pids)}  (overlap {len(overlap)})")
    print()
    if not problems:
        print("  CLEAN — every ok paper has exactly one final record, every record's")
        print("  item/scale/row structure matches master_flat.csv exactly, no paper")
        print("  exists in both auto/ and adjudicated/, no duplicate items.")
        return 0
    print("  PROBLEMS FOUND:")
    for k, v in problems.items():
        print(f"\n  -- {k} ({len(v)}) --")
        for item in v[:20]:
            print(f"     {item}")
        if len(v) > 20:
            print(f"     ... and {len(v) - 20} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
