#!/usr/bin/env python3
"""
refresh_tables.py — regenerate ONLY the summary + companion tables
(samples.csv / scales.csv / items.csv / summary.txt) from the existing
data/final/records/*.json, so they reflect the current 1,791-paper corpus.

It DOES NOT touch master_flat.csv (unlike 04_export.py, which rebuilds it).
Everything is read from the frozen per-paper records, so nothing is re-adjudicated
or repaired.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from common import load_env  # noqa: E402


def _imp(name, fn):
    spec = importlib.util.spec_from_file_location(name, ROOT / fn)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    load_env()
    exp = _imp("export_mod", "04_export.py")
    log = exp.read_log()

    docs = []
    for p in sorted(exp.RECORDS.glob("*.json")):
        doc = exp.rj(p)
        if not doc:
            continue
        docs.append((p.stem, log.get(p.stem, {}).get("filename", ""), doc))

    consensus = {pid: exp.consensus_items(pid) for pid, _, _ in docs}

    # companion tables (master_flat.csv is intentionally NOT written)
    sample_rows = exp.build_samples(docs)
    exp.wcsv(exp.FINAL / "samples.csv", sample_rows, exp.SAMPLES_CSV_COLS)
    exp.wcsv(exp.FINAL / "scales.csv", exp.build_scales(docs), exp.SCALES_CSV_COLS)
    exp.wcsv(exp.FINAL / "items.csv", exp.build_items(docs, consensus), exp.ITEMS_CSV_COLS)

    # counts, same definitions as 04_export's summary
    flat = exp.build_flat(docs, consensus)   # counted only, never written to disk
    n_items = sum(1 for r in flat if str(r.get("item_text_original", "")).strip())
    n_items_cons = sum(1 for r in flat if str(r.get("item_text_original", "")).strip()
                       and r.get("item_both_coders") is True)
    n_scale_rows = len({(r["paper_id"], r["scale_name"]) for r in flat if r.get("scale_name")})
    n_primary = sum(1 for r in sample_rows if str(r.get("is_primary")) == "True")
    n_adj = sum(1 for _, _, d in docs if d.get("provenance") == "adjudicated")
    n_auto = sum(1 for _, _, d in docs if d.get("provenance") == "auto_agreement")
    n_fallback = sum(1 for _, _, d in docs if d.get("provenance") == "coder_only_unresolved")

    lines = [
        f"corpus records (final) : {len(docs)}",
        f"  via adjudication     : {n_adj}",
        f"  via agreement only   : {n_auto}",
        f"  coder-only (unadjud.): {n_fallback}",
        f"flat rows (1 per item) : {len(flat)}",
        f"samples (all, incl 2nd): {len(sample_rows)}  ({n_primary} primary + "
        f"{len(sample_rows) - n_primary} secondary)  -> samples.csv",
        f"named scales           : {n_scale_rows}",
        f"items with text        : {n_items}",
        f"  both-coder consensus : {n_items_cons}"
        + (f" ({round(100 * n_items_cons / n_items)}%)" if n_items else ""),
        f"columns per row        : {len(exp.FLAT_COLS)}",
        "",
        "NOTE: refreshed from records/ by refresh_tables.py; master_flat.csv NOT rebuilt.",
    ]
    (exp.FINAL / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join("  " + l for l in lines))
    print(f"\n  wrote: summary.txt, samples.csv, scales.csv, items.csv "
          f"(master_flat.csv untouched)")


if __name__ == "__main__":
    main()
