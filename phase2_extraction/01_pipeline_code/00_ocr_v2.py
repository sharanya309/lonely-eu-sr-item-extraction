#!/usr/bin/env python3
"""
=============================================================================
 00_ocr_v2.py  —  EXACT COPY of 00_ocr.py + ONE logged policy change.
 (originals are kept unmodified for reporting the previous runs.)

 v2 DECISION (2026-08-23): PAGE-LIMIT EXCLUSION.
   PDFs with more than MAX_PAGES (=120) pages are AUTOMATICALLY excluded from
   OCR (most are long theses/books that blow up OCR cost + output length).
   They are:
     - detected with `pdfinfo` (poppler) before any OCR call,
     - logged to data/final/bad_source_files.csv  (problem = "over_page_limit"),
     - marked status="too_long" in data/papers_log.csv so they are NEVER retried,
     - recorded via log_event("00_ocr_v2", ...).
   Fail-open: if page count can't be read, the PDF is OCR'd as normal.
   Change MAX_PAGES below to adjust the threshold.
=============================================================================

STEP 00 — OCR via Gemini (gemini-2.5-flash-lite), BATCH. Native PDF vision:
one call per PDF transcribes body text, tables (as markdown), AND text inside
figures / charts / scanned images — no separate image handling needed.

    python3 00_ocr.py auto   --src data/pdfs --n 200   # Unattended: OCR 200 good papers.
                                                        # Non-PDF/unreadable files are
                                                        # logged to bad_source_files.csv,
                                                        # skipped, and it keeps pulling
                                                        # more PDFs to reach 200.
    python3 00_ocr.py submit --src data/pdfs --n 200   # one batch (manual)
    python3 00_ocr.py status
    python3 00_ocr.py retrieve

Each PDF is base64'd inline into a JSONL, uploaded, and run as one Gemini batch.
Resumable: PDFs that already have a data/markdown/<stem>.md are skipped, and the
JSONL is capped by size so huge corpora split into several batches automatically
(re-run submit after retrieve to send the next chunk).

Output: data/markdown/<pdf-stem>.md , data/papers_log.csv , data/ocr_usage.csv
Cost is token-billed (RATE["ocr"]) and logged to data/logs/.
"""
import base64
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from common import (LOG, MD_DIR, MODEL_ID, PDF_DIR, RATE, banner, load_env,
                    log_event, need, pid_of)

# v2 DECISION: hard page ceiling for OCR (see module docstring).
# 2026-08-23: raised 70 -> 120 to keep some long theses.
MAX_PAGES = 120


def _page_count(p):
    """Page count via `pdfinfo` (poppler, already on PATH). Returns int, or None
    if it can't be determined — callers then fail-open and OCR the file anyway."""
    try:
        out = subprocess.run(["pdfinfo", str(p)], capture_output=True,
                             text=True, timeout=30).stdout
        m = re.search(r"^Pages:\s+(\d+)", out, re.M)
        return int(m.group(1)) if m else None
    except Exception:
        return None

DATA = Path(__file__).resolve().parent / "data"
JOB = DATA / "ocr_job.json"
JSONL = DATA / "ocr_input.jsonl"
OCR_USAGE = DATA / "ocr_usage.csv"
MAX_BYTES = 100 * 1_000_000                    # cap JSONL per batch (base64 inflates ~33%)
MAX_OUT = 60000                                # markdown can be long

OCR_PROMPT = (
    "Transcribe this document to clean GitHub-flavored Markdown, preserving reading "
    "order. Rules:\n"
    "- Begin every page with a marker on its own line: `<!-- page N -->` (N = page number).\n"
    "- Render every table as a Markdown table. Do NOT summarise or omit tables.\n"
    "- Transcribe text inside figures, charts, diagrams, scanned images and photos "
    "verbatim, in place.\n"
    "- Reproduce questionnaire / scale items exactly, each item on its own line with its "
    "number or code — never paraphrase or skip them.\n"
    "- Output ONLY the transcription: no commentary, summaries, or descriptions."
)


def body(cid, b64):
    return {"key": f"ocr_{cid}", "request": {
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": "application/pdf", "data": b64}},
            {"text": OCR_PROMPT}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": MAX_OUT}}}


def _client():
    from google import genai
    return genai.Client(api_key=need("GEMINI_API_KEY", "GOOGLE_API_KEY"))


BAD_CSV = DATA / "final" / "bad_source_files.csv"


def _statuses(*keep):
    if not LOG.exists():
        return set()
    return {r["paper_id"] for r in csv.DictReader(open(LOG, encoding="utf-8"))
            if r.get("status") in keep}


def _ok_ids():
    return _statuses("ok")


def _skip_ids():
    # papers we must NOT re-attempt: already OCR'd (ok) or terminally bad
    # (not_pdf/error) or v2-excluded for length (too_long)
    return _statuses("ok", "not_pdf", "error", "too_long")


def _is_pdf(p):
    try:
        with open(p, "rb") as f:
            return f.read(5) == b"%PDF-"
    except Exception:
        return False


def _log_bad(items):
    """Append (filename, paper_id, problem) to bad_source_files.csv, deduped by filename."""
    BAD_CSV.parent.mkdir(parents=True, exist_ok=True)
    seen, rows = set(), []
    if BAD_CSV.exists():
        for r in csv.DictReader(open(BAD_CSV, encoding="utf-8")):
            seen.add(r["filename"]); rows.append(r)
    for fn, pid, prob in items:
        if fn not in seen:
            seen.add(fn); rows.append({"filename": fn, "paper_id": pid, "problem": prob})
    with open(BAD_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["filename", "paper_id", "problem"])
        w.writeheader(); w.writerows(rows)


def _mark_log(entries):
    """Upsert (paper_id, filename, status) rows into papers_log.csv."""
    log = {r["paper_id"]: r for r in csv.DictReader(open(LOG, encoding="utf-8"))} if LOG.exists() else {}
    for pid, fn, st in entries:
        log[pid] = {"paper_id": pid, "filename": fn, "status": st}
    with open(LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["paper_id", "filename", "status"])
        w.writeheader(); w.writerows(log.values())


# --------------------------------------------------------------- submit
def submit(src, n):
    """Send ONE batch of up to n PDFs still needing OCR. Non-PDF files (HTML pages
    saved as .pdf, etc.) are detected by header, logged to bad_source_files.csv, and
    skipped WITHOUT an OCR call. Returns the list of paper_ids actually submitted
    (or None if nothing was sent)."""
    if JOB.exists():
        print("  a batch is already submitted — use status / retrieve."); return None
    skip = _skip_ids()
    pdfs = sorted(Path(src).glob("*.pdf"))
    cand = [p for p in pdfs if pid_of(p) not in skip
            and not (MD_DIR / (p.stem + ".md")).exists()]
    # pre-filter: mark & log files that aren't real PDFs, and never OCR them.
    # v2: ALSO exclude PDFs longer than MAX_PAGES (logged, never OCR'd, never retried).
    valid, badlog, badrows, n_notpdf, n_long = [], [], [], 0, 0
    for p in cand:
        if not _is_pdf(p):
            badlog.append((pid_of(p), p.name, "not_pdf"))
            badrows.append((p.name, pid_of(p), "not a PDF (HTML/other; header not %PDF)"))
            n_notpdf += 1
            continue
        npg = _page_count(p)                       # v2 DECISION: page-limit exclusion
        if npg is not None and npg > MAX_PAGES:
            badlog.append((pid_of(p), p.name, "too_long"))
            badrows.append((p.name, pid_of(p), f"over_page_limit ({npg} pages > {MAX_PAGES})"))
            log_event("00_ocr_v2", f"exclude too_long {p.name} pages={npg} > {MAX_PAGES}")
            n_long += 1
            continue
        valid.append(p)
    if badlog:
        _mark_log(badlog); _log_bad(badrows)
        print(f"  skipped {n_notpdf} non-PDF + {n_long} over-{MAX_PAGES}-page file(s) "
              f"-> logged to {BAD_CSV.name}")
    if n:
        valid = valid[:n]
    if not valid:
        print("  nothing to OCR."); return None

    idx, size = {}, 0
    with open(JSONL, "w", encoding="utf-8") as f:
        for p in valid:
            cid = pid_of(p)
            b64 = base64.standard_b64encode(p.read_bytes()).decode()
            line = json.dumps(body(cid, b64)) + "\n"
            if idx and size + len(line) > MAX_BYTES:      # keep >=1 per batch
                break
            f.write(line); idx[cid] = p.stem; size += len(line)
    remaining = len(valid) - len(idx)
    banner("00_ocr submit")
    print(f"  this batch: {len(idx)} PDFs | JSONL {size/1e6:.1f} MB | {MODEL_ID['ocr']}")
    if remaining:
        print(f"  ({remaining} more valid PDFs queued — resumable)")

    c = _client()
    up = c.files.upload(file=str(JSONL), config={"mime_type": "application/jsonl"})
    for _ in range(60):                                   # wait for file ACTIVE
        st = c.files.get(name=up.name).state
        if (st.name if hasattr(st, "name") else str(st)) == "ACTIVE":
            break
        time.sleep(3)
    jid = c.batches.create(model=MODEL_ID["ocr"], src=up.name,
                           config={"display_name": "ocr"}).name
    JOB.write_text(json.dumps({"job_id": jid, "map": idx}, indent=2))
    print(f"  submitted: {jid}\n  Next: python3 00_ocr.py status")
    log_event("00_ocr", f"submit {MODEL_ID['ocr']} n={len(idx)} queued={remaining} job={jid}")
    return list(idx.keys())


# --------------------------------------------------------------- status
def _state(c, jid):
    s = c.batches.get(name=jid).state
    s = s.name if hasattr(s, "name") else str(s)
    return "done" if "SUCCEEDED" in s else ("failed" if "FAILED" in s else "running")


def status():
    banner("00_ocr status")
    if not JOB.exists():
        print("  not submitted."); return
    j = json.loads(JOB.read_text())
    c = _client()
    st = _state(c, j["job_id"])
    done = len(list(MD_DIR.glob("*.md"))) if MD_DIR.exists() else 0
    print(f"  batch {j['job_id']}: {st} | markdowns on disk: {done}")
    print("\n  When 'done': python3 00_ocr.py retrieve\n")


# --------------------------------------------------------------- retrieve
def retrieve():
    if not JOB.exists():
        print("  not submitted."); return
    j = json.loads(JOB.read_text())
    c = _client()
    if _state(c, j["job_id"]) != "done":
        print(f"  not ready (state={_state(c, j['job_id'])}). Try later."); return
    job = c.batches.get(name=j["job_id"])
    raw = c.files.download(file=job.dest.file_name).decode("utf-8")

    MD_DIR.mkdir(parents=True, exist_ok=True)
    log = {r["paper_id"]: r for r in csv.DictReader(open(LOG, encoding="utf-8"))} \
        if LOG.exists() else {}
    usage, n_ok, errored = [], 0, []
    for ln in raw.strip().splitlines():
        if not ln.strip():
            continue
        rec = json.loads(ln)
        cid = rec.get("key", "").replace("ocr_", "", 1)
        stem = j["map"].get(cid, cid)
        resp = rec.get("response") or {}
        cands = resp.get("candidates") or []
        parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            log[cid] = {"paper_id": cid, "filename": stem + ".pdf", "status": "error"}
            errored.append((stem + ".pdf", cid, "OCR returned no text (scanned/image-only, refused, or corrupt)"))
            continue
        (MD_DIR / (stem + ".md")).write_text(text, encoding="utf-8")
        st = "ok" if len(text) > 500 else "poor"
        log[cid] = {"paper_id": cid, "filename": stem + ".pdf", "status": st}
        um = resp.get("usageMetadata") or {}
        it, ot = um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0)
        cost = it / 1e6 * RATE["ocr"]["in"] + ot / 1e6 * RATE["ocr"]["out"]
        usage.append({"paper_id": cid, "in_tok": it, "out_tok": ot, "cost_usd": round(cost, 6)})
        n_ok += 1

    with open(LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["paper_id", "filename", "status"])
        w.writeheader(); w.writerows(log.values())
    if errored:
        _log_bad(errored)      # real PDFs that OCR couldn't read -> bad_source_files.csv
    if usage:
        ex = OCR_USAGE.exists()
        with open(OCR_USAGE, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["paper_id", "in_tok", "out_tok", "cost_usd"])
            if not ex:
                w.writeheader()
            w.writerows(usage)
    JOB.unlink(missing_ok=True)                   # clear so the next submit works
    total = sum(u["cost_usd"] for u in usage)
    banner("00_ocr retrieve")
    print(f"  papers ok: {n_ok} | ${total:.4f}  (${total/max(n_ok,1):.5f}/paper)")
    log_event("00_ocr", f"retrieve ok={n_ok} cost=${total:.4f}")
    print("  Check a data/markdown/*.md for tables + '<!-- page N -->' markers.")
    print("  More to OCR? re-run submit. Else: python3 00_subsample.py --n 100\n")


def auto(src, n, poll=60):
    """Unattended: OCR until n papers have SUCCESSFULLY OCR'd (n omitted = all
    remaining), across as many 100MB batches as needed. `--n 200` means 200 GOOD
    papers: bad source files (non-PDF, or PDFs OCR can't read) are logged to
    bad_source_files.csv, skipped, and the loop keeps pulling more PDFs to reach n.
    Resumable; stops when n successes are reached or there are no PDFs left to try."""
    banner("00_ocr auto — OCR N good papers, skipping+logging bad files")
    start_ok = len(_ok_ids())
    c = _client()
    while True:
        got = len(_ok_ids()) - start_ok
        if n and got >= n:
            break
        need = (n - got) if n else None
        if not JOB.exists():
            submitted = submit(src, need)     # skips ok/not_pdf/error; pre-filters non-PDFs
            if not submitted:
                print("  no more OCR-able PDFs left to try."); break
        while True:
            try:
                st = _state(c, json.loads(JOB.read_text())["job_id"])
            except Exception as e:
                print("  status error:", str(e)[:130]); time.sleep(poll); continue
            md = len(list(MD_DIR.glob("*.md"))) if MD_DIR.exists() else 0
            print(f"  ocr batch: {st}  ({md} markdowns on disk)")
            if st in ("done", "failed"):
                retrieve(); break
            time.sleep(poll)
    got = len(_ok_ids()) - start_ok
    nbad = sum(1 for _ in csv.DictReader(open(BAD_CSV, encoding="utf-8"))) if BAD_CSV.exists() else 0
    tail = f" (target {n})" if n else ""
    print(f"\n  Done. OCR: {got} new papers OCR'd{tail}. Bad files logged: {nbad} "
          f"-> {BAD_CSV.name}. Next: python3 01_extract.py auto\n")


def main():
    load_env()
    act = sys.argv[1] if len(sys.argv) > 1 else ""
    argv = sys.argv[2:]
    src = argv[argv.index("--src") + 1] if "--src" in argv else str(PDF_DIR)
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else None
    if act == "submit":
        submit(src, n)
    elif act == "status":
        status()
    elif act == "retrieve":
        retrieve()
    elif act == "auto":
        auto(src, n)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
