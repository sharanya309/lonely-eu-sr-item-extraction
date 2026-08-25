#!/usr/bin/env python3
"""
run_append_v2.py — EXACT COPY of run_append.py, except it drives the _v2 stage
scripts (00_ocr_v2.py, 01_extract_v2.py) so the two v2 policies apply:
  * OCR excludes PDFs > 70 pages   (00_ocr_v2.py)
  * extraction gives up on a paper after 2 failed attempts, so auto never hangs
    on the ~3 perma-failing Gemini papers  (01_extract_v2.py)
Everything else (02_agreement.py, 03_adjudicate.py, the append logic) is identical
to run_append.py, and the originals are left untouched for reporting.

Unattended: process every REMAINING pdf and APPEND the new papers
to the existing data/final/master_flat.csv WITHOUT touching a single existing row.

What it does, in one command:
    1. 00_ocr_v2.py auto     OCR all remaining PDFs (skips done/bad + >70pg)   [v2]
    2. 01_extract_v2.py auto both coders extract; skip after 2 failed tries     [v2]
    3. 02_agreement.py       IRR + route disputes to the judge                 [existing]
    4. 03_adjudicate submit -> poll -> retrieve   judge the disputes           [existing]
       (deliberately WITHOUT its auto's 04_export step, which would rebuild the CSV)
    5. append                build ONLY the new papers, write a SEPARATE csv
       (master_flat_new.csv), then append those rows to master_flat.csv.

Guarantees for master_flat.csv:
    - existing rows are NEVER read-modified-rewritten. The file is opened in
      APPEND mode ("a") and only new-paper rows are added, in its existing column order.
    - the "repair" safety-nets (restore_empty_sections / normalize_enums) run ONLY
      on brand-new papers, never on your existing 1658.
    - a paper already present in master_flat.csv is skipped, so re-running is safe
      (idempotent — it will just say "nothing new to append").

Usage:
    python3 run_append.py            # full remaining pipeline, then append
    python3 run_append.py append     # ONLY the append step (if 00-03 already ran)

Note: only master_flat.csv (+ its per-paper records/) is appended. The companion
tables samples.csv / scales.csv / items.csv are NOT updated here — run 04_export.py
if you want those rebuilt (that one does a full rebuild).
"""
import csv
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from common import FINAL, load_env  # noqa: E402

MASTER = FINAL / "master_flat.csv"
MASTER_NEW = FINAL / "master_flat_new.csv"
ADJ_JOB = FINAL / "adjudicate_job.json"


def _import_numbered(mod_name, filename):
    """Import a module whose filename starts with a digit (can't be `import`ed)."""
    spec = importlib.util.spec_from_file_location(mod_name, ROOT / filename)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(*cmd):
    print(f"\n$ {' '.join(cmd)}\n")
    r = subprocess.run([sys.executable, *cmd], cwd=str(ROOT))
    if r.returncode != 0:
        sys.exit(f"  step failed ({' '.join(cmd)}) — fix and re-run. Safe to resume.")


# ---------------------------------------------------------------- stages 00-03
def stages_00_to_03(poll=60):
    run("00_ocr_v2.py", "auto")         # all remaining PDFs (v2: skips >70-page files)
    run("01_extract_v2.py", "auto")     # both coders (v2: give up after 2 failed tries)
    run("02_agreement.py")              # local, instant

    # 03: submit -> poll -> retrieve, WITHOUT the auto's 04_export rebuild.
    run("03_adjudicate.py", "submit")
    if ADJ_JOB.exists():
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        client = anthropic.Anthropic(api_key=key)
        jid = json.loads(ADJ_JOB.read_text())["job_id"]
        while True:
            try:
                st = client.messages.batches.retrieve(jid).processing_status
            except Exception as e:
                print("  judge status error:", str(e)[:140]); time.sleep(poll); continue
            done = len(list((FINAL / "adjudicated").glob("*.json")))
            print(f"  judge: {st}  ({done} adjudicated)")
            if st == "ended":
                break
            time.sleep(poll)
        run("03_adjudicate.py", "retrieve")
    else:
        print("  nothing to adjudicate (all papers agreed) — skipping judge.")


# ---------------------------------------------------------------- append step
def existing_master():
    """(set of paper_ids already in master_flat.csv, its exact header order)."""
    if not MASTER.exists():
        sys.exit(f"  {MASTER} not found — nothing to append to. Run 04_export.py once first.")
    with open(MASTER, encoding="utf-8") as f:
        r = csv.DictReader(f)
        header = list(r.fieldnames or [])
        pids = {row["paper_id"] for row in r}
    return pids, header


def build_new_docs(exp, existing):
    """Mirror 04_export's record-building, but ONLY for papers NOT already in
    master_flat.csv. Repairs (normalize_enums / restore_empty_sections) therefore
    only ever touch new papers. Writes a records/<pid>.json for each new paper."""
    log = exp.read_log()
    docs, seen = [], set()
    for src in (exp.FINAL / "adjudicated", exp.FINAL / "auto"):
        if not src.exists():
            continue
        for p in sorted(src.glob("*.json")):
            pid = p.stem
            if pid in existing or pid in seen:
                continue
            doc = exp.rj(p)
            if not doc:
                continue
            doc = exp.normalize_enums(doc)
            doc, _ = exp.restore_empty_sections(
                doc, exp.rj(exp.CODERS / "gemini" / "results" / f"{pid}.json"),
                exp.rj(exp.CODERS / "openai" / "results" / f"{pid}.json"))
            seen.add(pid)
            exp.RECORDS.mkdir(parents=True, exist_ok=True)
            (exp.RECORDS / p.name).write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            docs.append((pid, log.get(pid, {}).get("filename", ""), doc))

    # backstop: new papers with no auto/adjudicated record -> verified coder union
    for pid in sorted(exp.sub_papers()):
        if pid in existing or pid in seen:
            continue
        a = exp.rj(exp.CODERS / "gemini" / "results" / f"{pid}.json")
        b = exp.rj(exp.CODERS / "openai" / "results" / f"{pid}.json")
        base = a or b
        if not base:
            continue
        ns = exp.norm(exp.trim_md(exp.md_text(pid)))
        base["scales"] = exp.resolve.resolve_items([a, b], ns)
        base["provenance"] = "coder_only_unresolved"
        meta = base.get("extraction_meta") if isinstance(base.get("extraction_meta"), dict) else {}
        meta["needs_human_review"] = True
        meta.setdefault("extraction_notes", "")
        meta["extraction_notes"] = (meta["extraction_notes"]
                                    + " | NOT adjudicated: exported from coder output.").strip(" |")
        base["extraction_meta"] = meta
        base = exp.normalize_enums(base)
        seen.add(pid)
        exp.RECORDS.mkdir(parents=True, exist_ok=True)
        (exp.RECORDS / f"{pid}.json").write_text(
            json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
        docs.append((pid, log.get(pid, {}).get("filename", ""), base))
    return docs


def append_new():
    exp = _import_numbered("export_mod", "04_export.py")
    existing, header = existing_master()
    print(f"  existing master_flat.csv: {len(existing)} papers, {len(header)} columns")

    docs = build_new_docs(exp, existing)
    if not docs:
        print("  nothing new to append — master_flat.csv already covers every paper.")
        return

    consensus = {pid: exp.consensus_items(pid) for pid, _, _ in docs}
    new_rows = exp.build_flat(docs, consensus)

    # column-order sanity: append using the FILE's existing header so rows line up.
    if set(header) != set(exp.FLAT_COLS):
        print("  WARNING: master_flat.csv columns differ from the current schema; "
              "appending on the file's existing header (extra new fields are dropped).")

    # 1) SEPARATE csv of just the new papers (full current schema, with header)
    with open(MASTER_NEW, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=exp.FLAT_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(new_rows)

    # 2) APPEND those rows to the existing master_flat.csv — no header, existing
    #    column order, existing rows untouched (file opened in append mode).
    with open(MASTER, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        for r in new_rows:
            w.writerow({c: r.get(c, "") for c in header})

    n_new_papers = len(docs)
    print(f"\n  Done: appended {len(new_rows)} rows for {n_new_papers} new paper(s).")
    print(f"    separate csv : {MASTER_NEW}")
    print(f"    appended to  : {MASTER}  (existing rows untouched)")
    print(f"    now {len(existing) + n_new_papers} papers total in master_flat.csv")
    print("  (companion tables samples/scales/items were NOT changed — run 04_export.py "
          "if you want those rebuilt.)")


def main():
    load_env()
    if len(sys.argv) > 1 and sys.argv[1] == "append":
        append_new()
        return
    stages_00_to_03()
    print("\n=== APPEND NEW PAPERS -> master_flat.csv ===")
    append_new()
    print("\n  Done. Optional audit: python3 07_verify.py   |   costs: python3 05_costs.py\n")


if __name__ == "__main__":
    main()
