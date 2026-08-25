#!/usr/bin/env python3
"""
STEP 04 — FINAL export. One flat CSV with every schema.py field, one row per item.

Outputs in data/final/:
    master_flat.csv        THE deliverable — one row per item, all 59 fields joined
                           on (paper + pdf_quality + primary sample demographics +
                           scale + item + extraction/adjudication meta)
    records/<pid>.json     lossless canonical record per paper (full multi-sample
                           structure; adjudicated wins over auto)
    summary.txt            counts
"""
import csv
import json
from pathlib import Path

import resolve
import schema
from common import (CODERS, FINAL, banner, log_event, md_text, norm, read_log,
                   restore_empty_sections, sub_papers, trim_md)

RECORDS = FINAL / "records"

# Canonicalise enum CASING across every source (auto/adjudicated/fallback) so a
# categorical value never appears two ways (e.g. "Validation" vs "validation")
# and nothing silently drops out of a filter/group-by downstream.
def _canon(val, allowed):
    if isinstance(val, str):
        for a in allowed:
            if val.lower() == a.lower():
                return a
    return val


def normalize_enums(doc):
    p = doc.get("paper")
    if isinstance(p, dict) and "study_type" in p:
        p["study_type"] = _canon(p["study_type"], schema.STUDY_TYPES)
    q = doc.get("pdf_quality")
    if isinstance(q, dict) and "quality_flag" in q:
        q["quality_flag"] = _canon(q["quality_flag"], schema.QUALITY)
    m = doc.get("extraction_meta")
    if isinstance(m, dict) and "extraction_confidence" in m:
        m["extraction_confidence"] = _canon(m["extraction_confidence"], schema.CONFIDENCE)
    for s in doc.get("samples") or []:
        if isinstance(s, dict):
            if "age_format" in s:
                s["age_format"] = _canon(s["age_format"], schema.AGE_FORMATS)
            if "gender_format" in s:
                s["gender_format"] = _canon(s["gender_format"], schema.GENDER_FORMATS)
    for s in doc.get("scales") or []:
        if isinstance(s, dict) and "items_coverage" in s:
            s["items_coverage"] = _canon(s["items_coverage"], schema.COVERAGE)
    return doc

# Column lists taken directly from schema.py's obj({...}) key lists.
PAPER_COLS = ["title", "year", "language", "country_study", "study_type"]
QUALITY_COLS = ["text_extractable", "has_questionnaire_content", "quality_flag",
                "quality_notes"]
SAMPLE_COLS = [
    "sample_label", "is_primary", "is_multi_population", "other_populations_note",
    "total_n", "population_type", "country_location",
    "age_mean", "age_sd", "age_range_min", "age_range_max", "age_notes", "age_format",
    "gender_pct_female", "gender_n_female", "gender_pct_male", "gender_n_male",
    "gender_pct_other", "gender_n_other", "gender_notes", "gender_format",
]
SCALE_COLS = [
    "scale_name", "scale_abbreviation", "scale_citation", "which_sample",
    "scale_evidence_quote", "total_items_in_scale", "items_coverage",
    "response_format", "subscales", "items_extracted_count",
    "scale_name_verified",   # True if the scale name/abbrev/quote is printed in the source
]
ITEM_COLS = ["item_number", "subscale", "item_text_original", "item_text_english",
             "shared_stem", "reverse_scored", "source_page"]
# Robustness flag: True when this item was independently extracted AND
# source-verified by BOTH coders (the intersection), vs the union that ships by default.
# Filter master_flat to item_both_coders == True to re-run the main analysis on the
# consensually-coded item subset and confirm conclusions don't shift.
CONSENSUS_COLS = ["item_both_coders"]
EXTRACT_META_COLS = ["extraction_confidence", "confidence_reason", "extraction_notes",
                     "total_scales_found", "total_items_extracted"]
ADJUDICATE_ONLY_COLS = ["needs_human_review", "overruled_summary"]
JOIN_COLS = ["paper_id", "filename", "provenance"]

# One fully-joined row per item: paper + primary sample + scale + item + meta.
# This is the single flat "everything" sheet (rebuilds the old master layout).
FLAT_COLS = (["paper_id", "filename", "provenance", "doi", "url"]
             + PAPER_COLS + QUALITY_COLS + SAMPLE_COLS + SCALE_COLS + ITEM_COLS
             + CONSENSUS_COLS + EXTRACT_META_COLS + ADJUDICATE_ONLY_COLS)

# Normalized companion tables — one row per entity — so NOTHING is dropped when a
# study has multiple samples. master_flat shows only the PRIMARY sample per item
# row; samples.csv lists EVERY sample. scales.csv / items.csv are tidy per-entity
# sheets for analysis and OSF.
SAMPLES_CSV_COLS = ["paper_id", "filename", "provenance", "title", "study_type"] + SAMPLE_COLS
SCALES_CSV_COLS = ["paper_id", "filename", "provenance", "title"] + SCALE_COLS
ITEMS_CSV_COLS = (["paper_id", "filename", "scale_name", "scale_abbreviation", "which_sample"]
                  + ITEM_COLS + CONSENSUS_COLS)


def doi_url(fn):
    """Best-effort DOI/URL parsed from the filename (e.g.
    '..._10.1186@@@s41155-021-00194-9' -> '10.1186/s41155-021-00194-9').
    Purely cosmetic; blank if the pattern isn't there."""
    if not fn:
        return "", ""
    stem = Path(fn).stem
    cand = stem.split("_", 1)[1] if "_" in stem else stem
    if not cand.startswith("10."):
        return "", ""
    doi = cand.replace("@@@", "/").replace("@", "/")
    if "/" not in doi and "_" in doi:          # some names use '_' as the slash
        doi = doi.replace("_", "/", 1)
    return doi, "https://doi.org/" + doi


def rj(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def _pre_adjudication_item_union():
    """The count of distinct source-verified items across both coders (the union),
    written by 02_agreement into agreement_report.csv as the 'n' of the
    item_overlap_both_pct row. Used only for a before/after line in the summary.
    Returns None if step 02 hasn't run."""
    p = FINAL / "agreement_report.csv"
    if not p.exists():
        return None
    try:
        for r in csv.DictReader(open(p, encoding="utf-8")):
            if r.get("field") == "item_overlap_both_pct":
                return int(r["n"])
    except Exception:
        return None
    return None


def consensus_items(pid):
    """The item_keys BOTH coders independently extracted AND that verify against the
    source text (intersection). Empty for single-coder papers — no consensus possible.
    Uses the same source-verification and item_key as resolve.py, so these keys line
    up 1:1 with the items that ship in the final record."""
    a = rj(CODERS / "gemini" / "results" / f"{pid}.json")
    b = rj(CODERS / "openai" / "results" / f"{pid}.json")
    if not a or not b:
        return set()
    ns = norm(md_text(pid))
    return resolve.verified_item_set(a, ns) & resolve.verified_item_set(b, ns)


def paper_join(doc, pid, fn):
    p = doc.get("paper") or {}
    row = {"paper_id": pid, "filename": fn, "provenance": doc.get("provenance")}
    row.update({c: p.get(c) for c in PAPER_COLS})
    q = doc.get("pdf_quality") or {}
    row.update({c: q.get(c) for c in QUALITY_COLS})
    return row


def build_flat(docs, consensus):
    """One row per item with EVERY extracted field joined on: paper, pdf_quality,
    the PRIMARY sample's full demographics, the scale, the item, and meta. Scales
    with no items still emit one row (item cols blank); papers with no scales emit
    one row (scale + item cols blank). Nothing is dropped. `consensus` maps
    paper_id -> set of both-coder item_keys, used to flag item_both_coders."""
    rows = []

    def row(**parts):
        r = {c: "" for c in FLAT_COLS}                  # stable order, no missing cols
        r.update({k: v for k, v in parts.items() if k in r})
        return r

    for pid, fn, doc in docs:
        cons = consensus.get(pid, set())
        head = paper_join(doc, pid, fn)                 # ids + PAPER_COLS + QUALITY_COLS
        doi, url = doi_url(fn)
        head.update({"doi": doi, "url": url})
        meta = doc.get("extraction_meta") or {}
        mcols = {c: meta.get(c) for c in EXTRACT_META_COLS + ADJUDICATE_ONLY_COLS}
        prim = next((s for s in doc.get("samples") or [] if s.get("is_primary")),
                    (doc.get("samples") or [None])[0])
        scols = {c: (prim.get(c) if prim else None) for c in SAMPLE_COLS}

        scales = doc.get("scales") or []
        if not scales:
            rows.append(row(**head, **scols, **mcols))
            continue
        for sc in scales:
            sccols = {c: sc.get(c) for c in SCALE_COLS}
            items = sc.get("items") or []
            if not items:
                rows.append(row(**head, **scols, **sccols, **mcols))
                continue
            for it in items:
                icols = {c: it.get(c) for c in ITEM_COLS}
                icols["item_both_coders"] = resolve.item_key(it) in cons
                rows.append(row(**head, **scols, **sccols, **icols, **mcols))
    return rows


def build_samples(docs):
    """One row per sample across the corpus — EVERY sample, not just the primary —
    so multi-sample studies lose no population data (the gap master_flat has)."""
    rows = []
    for pid, fn, doc in docs:
        p = doc.get("paper") or {}
        head = {"paper_id": pid, "filename": fn, "provenance": doc.get("provenance"),
                "title": p.get("title"), "study_type": p.get("study_type")}
        samples = doc.get("samples") or []
        if not samples:
            rows.append(dict(head))                       # paper with no sample still appears
            continue
        for s in samples:
            r = dict(head); r.update({c: s.get(c) for c in SAMPLE_COLS}); rows.append(r)
    return rows


def build_scales(docs):
    """One row per scale across the corpus (with scale_name_verified + coverage)."""
    rows = []
    for pid, fn, doc in docs:
        p = doc.get("paper") or {}
        head = {"paper_id": pid, "filename": fn, "provenance": doc.get("provenance"),
                "title": p.get("title")}
        for s in doc.get("scales") or []:
            r = dict(head); r.update({c: s.get(c) for c in SCALE_COLS}); rows.append(r)
    return rows


def build_items(docs, consensus):
    """One row per item across the corpus, tagged with its scale + consensus flag."""
    rows = []
    for pid, fn, doc in docs:
        cons = consensus.get(pid, set())
        for s in doc.get("scales") or []:
            for it in s.get("items") or []:
                r = {"paper_id": pid, "filename": fn, "scale_name": s.get("scale_name"),
                     "scale_abbreviation": s.get("scale_abbreviation"),
                     "which_sample": s.get("which_sample")}
                r.update({c: it.get(c) for c in ITEM_COLS})
                r["item_both_coders"] = resolve.item_key(it) in cons
                rows.append(r)
    return rows


def dedupe(cols):
    seen, out = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def wcsv(path, rows, cols=None):
    if not rows:
        return
    cols = dedupe(cols) if cols else list(rows[0])
    for r in rows:
        for c in cols:
            r.setdefault(c, "")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    banner("04_export")
    log_event("04_export", "START")
    RECORDS.mkdir(parents=True, exist_ok=True)
    log = read_log()
    docs, seen = [], set()
    n_adj = n_auto = 0
    for src, tag in ((FINAL / "adjudicated", "adjudicated"), (FINAL / "auto", "auto")):
        if not src.exists():
            continue
        for p in sorted(src.glob("*.json")):
            if p.stem in seen:
                continue
            doc = rj(p)
            if not doc:
                continue
            doc = normalize_enums(doc)
            # SAFETY NET: if this record (usually adjudicated) is missing population
            # or quality the coders had, restore it here — repairs existing records
            # on a plain re-run of 04, no judge re-run needed.
            doc, _ = restore_empty_sections(
                doc, rj(CODERS / "gemini" / "results" / f"{p.stem}.json"),
                rj(CODERS / "openai" / "results" / f"{p.stem}.json"))
            seen.add(p.stem)
            (RECORDS / p.name).write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            docs.append((p.stem, log.get(p.stem, {}).get("filename", ""), doc))
            n_adj += tag == "adjudicated"
            n_auto += tag == "auto"

    # Backstop: guarantee every paper in the corpus is exported. If a paper never
    # got an auto/ or adjudicated/ record (e.g. a judge paper was skipped), fall
    # back to its best coder extraction — items VERIFIED against source so no
    # fabricated item leaks in — and flag it for human review. Nothing is dropped.
    n_fallback = 0
    for pid in sorted(sub_papers()):
        if pid in seen:
            continue
        a = rj(CODERS / "gemini" / "results" / f"{pid}.json")
        b = rj(CODERS / "openai" / "results" / f"{pid}.json")
        base = a or b
        if not base:
            continue
        ns = norm(trim_md(md_text(pid)))
        base["scales"] = resolve.resolve_items([a, b], ns)   # verified union; None ignored
        base["provenance"] = "coder_only_unresolved"
        meta = base.get("extraction_meta") if isinstance(base.get("extraction_meta"), dict) else {}
        meta["needs_human_review"] = True
        meta.setdefault("extraction_notes", "")
        meta["extraction_notes"] = (meta["extraction_notes"] + " | NOT adjudicated: exported from coder output.").strip(" |")
        base["extraction_meta"] = meta
        base = normalize_enums(base)
        seen.add(pid)
        (RECORDS / f"{pid}.json").write_text(
            json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
        docs.append((pid, log.get(pid, {}).get("filename", ""), base))
        n_fallback += 1
    if n_fallback:
        print(f"  WARNING: {n_fallback} paper(s) exported from coder output (not adjudicated) "
              "— flagged needs_human_review.")

    # THE single final deliverable: one flat CSV, every field, one row per item.
    consensus = {pid: consensus_items(pid) for pid, _, _ in docs}
    flat = build_flat(docs, consensus)
    wcsv(FINAL / "master_flat.csv", flat, FLAT_COLS)

    # Normalized companion tables so nothing is lost for multi-sample studies etc.
    sample_rows = build_samples(docs)
    wcsv(FINAL / "samples.csv", sample_rows, SAMPLES_CSV_COLS)
    wcsv(FINAL / "scales.csv", build_scales(docs), SCALES_CSV_COLS)
    wcsv(FINAL / "items.csv", build_items(docs, consensus), ITEMS_CSV_COLS)
    n_primary = sum(1 for r in sample_rows if str(r.get("is_primary")) == "True")

    n_items = sum(1 for r in flat if str(r.get("item_text_original", "")).strip())
    n_items_consensus = sum(1 for r in flat
                            if str(r.get("item_text_original", "")).strip()
                            and r.get("item_both_coders") is True)
    n_scale_rows = len({(r["paper_id"], r["scale_name"]) for r in flat if r.get("scale_name")})
    n_corpus = len(sub_papers())
    pre_adj_items = _pre_adjudication_item_union()   # verified union from step 02 (or None)
    lines = [f"corpus records (final) : {len(docs)} of {n_corpus} in corpus"
             + ("  <-- MISSING SOME" if len(docs) < n_corpus else "  (complete)"),
             f"  via adjudication     : {n_adj}",
             f"  via agreement only   : {n_auto}",
             f"  coder-only (unadjud.): {n_fallback}",
             f"flat rows (1 per item) : {len(flat)}",
             f"samples (all, incl 2nd): {len(sample_rows)}  ({n_primary} primary + "
             f"{len(sample_rows) - n_primary} secondary)  -> samples.csv",
             f"named scales           : {n_scale_rows}",
             f"items with text        : {n_items}",
             f"  both-coder consensus : {n_items_consensus}"
             + (f" ({round(100 * n_items_consensus / n_items)}%)" if n_items else "")
             + "  [item_both_coders=True -> robustness subset]",
             (f"items pre-adjudication : {pre_adj_items} (verified union, step 02) "
              f"-> {n_items} final ({n_items - pre_adj_items:+d} after judge curation)"
              if pre_adj_items is not None else
              "items pre-adjudication : n/a (run 02_agreement first for before/after)"),
             f"columns per row        : {len(FLAT_COLS)}"]
    (FINAL / "summary.txt").write_text("\n".join(lines) + "\n")

    banner("04_export — single flat CSV (every field, one sheet)")
    for l in lines:
        print("  " + l)
    print(f"\n  FINAL: {FINAL / 'master_flat.csv'}  ({len(FLAT_COLS)} columns, primary sample)")
    print(f"  normalized tables (nothing dropped): samples.csv (ALL samples), "
          "scales.csv, items.csv")
    print(f"  lossless per-paper JSON (full multi-sample detail): {RECORDS}/")
    log_event("04_export",
              f"DONE records={len(docs)} (adj={n_adj} auto={n_auto}) "
              f"flat_rows={len(flat)} items={n_items} cols={len(FLAT_COLS)}")
    print()


if __name__ == "__main__":
    main()
