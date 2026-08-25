#!/usr/bin/env python3
"""Shared helpers — v3 tiered pipeline.

Drop this folder's contents into a directory that will hold data/. Copy your
existing data/markdown/ and data/papers_log.csv (from OCR) in before running
anything — nothing here touches OCR.
"""
import csv
import datetime
import hashlib
import os
import re
import sys
import unicodedata
from pathlib import Path


def pid_of(pdf):
    """Stable 12-char paper id from the PDF filename (unchanged across OCR runs)."""
    return hashlib.md5(Path(pdf).name.encode()).hexdigest()[:12]

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

PDF_DIR = DATA / "pdfs"
MD_DIR = DATA / "markdown"
CODERS = DATA / "coders"
COMPARE = DATA / "compare"
FINAL = DATA / "final"
LOGS = DATA / "logs"

MANIFEST = DATA / "manifest.csv"
LOG = DATA / "papers_log.csv"
SUBSAMPLE = DATA / "subsample.csv"


def log_event(step, msg):
    """Append a timestamped line to data/logs/pipeline.log (and a per-step log).
    Returns the message so callers can `print(log_event(...))` to tee to console.
    Never raises — logging must not break a run."""
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts}  [{step:<13}]  {msg}\n"
        with open(LOGS / "pipeline.log", "a", encoding="utf-8") as f:
            f.write(line)
        with open(LOGS / f"{step}.log", "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    return msg


def tee(step, msg):
    """Print to console AND log it."""
    print(msg)
    log_event(step, msg)

# ---------------------------------------------------------------------------
# Models & list rates (USD / 1M tokens, BATCH where a batch tier exists).
# Token counts always come from the provider; only rates are estimates —
# reconcile against provider usage dashboards.
# ---------------------------------------------------------------------------
MODEL_ID = {
    "gemini": "gemini-2.5-flash",             # coder A
    "openai": "gpt-5.4-mini",                  # coder B — GPT-5.4-mini (reasoning model,
                                             # higher batch queue limit; strict
                                             # structured output guaranteed. Rejects
                                             # temperature/max_tokens; 01_extract sends
                                             # reasoning_effort + max_completion_tokens).
    "judge":  "claude-haiku-4-5-20251001",    # adjudicator — resolves disagreeing papers,
                                             # incl. scale/subscale/item disputes (items it
                                             # returns are still source-verified downstream)
    "ocr":    "gemini-2.5-flash-lite",         # step 00 OCR — native PDF vision
                                             # (text + tables + figure text), cheapest
}
RATE = {
    # BATCH prices (50% off list) — this pipeline uses the Batch API for ALL model
    # calls (01 gemini+openai, 03 anthropic), so cost is estimated at batch rates.
    # Reconcile against your provider dashboards.
    "gemini": {"in": 0.15,  "out": 1.25},     # gemini-2.5-flash batch (list 0.30/2.50)
    "openai": {"in": 0.125, "out": 1.00},     # gpt-5.4-mini batch (list 0.25/2.00)
    "judge":  {"in": 0.50,  "out": 2.50},     # claude-haiku-4.5 batch (list 1.00/5.00)
    "ocr":    {"in": 0.05,  "out": 0.20},     # gemini-2.5-flash-lite batch (list 0.10/0.40)
}
OCR_PER_1000_PAGES = 5.0                       # (legacy Mistral per-page rate; unused now
                                             # that OCR is token-billed via RATE["ocr"])
N_FULL = 200                                   # your review corpus size


def load_env():
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            # A value deliberately supplied in the terminal wins.  This lets
            # you rotate an API key without an old .env value silently
            # replacing it; .env remains the fallback for new terminals.
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def need(*names):
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    sys.exit(f"FATAL: none of {names} found in .env")


_PUNCT = {'\u201c': '"', '\u201d': '"', '\u2019': "'", '\u2018': "'",
          '\u2013': '-', '\u2014': '-', '\u00a0': ' '}


def norm(s):
    """Aggressive text normalisation used for all string comparison. Collapses
    hyphenation/line-break artefacts from OCR so containment checks survive
    them."""
    if s is None:
        return ""
    # casefold() (not lower()) for correct CASELESS matching across languages —
    # handles cases lower() misses, e.g. German ß<->ss, Greek final sigma, Cyrillic.
    # NFKC first folds width/compatibility variants so multilingual OCR text aligns.
    s = unicodedata.normalize("NFKC", str(s)).casefold()
    for a, b in _PUNCT.items():
        s = s.replace(a, b)
    s = re.sub(r'[*_`~]', '', s)
    s = s.replace('|', ' ')
    s = re.sub(r'-\s*\n\s*', '', s)          # de-hyphenate across line breaks
    s = re.sub(r'^\s*[a-z]?\d*[-.\d]*\s*[\.\)\:]\s*', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s.rstrip('.').strip()


def num(x):
    if x is None or x == "":
        return None
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None


def read_log():
    if not LOG.exists():
        sys.exit("FATAL: data/papers_log.csv missing — OCR must exist already.")
    return {r["paper_id"]: r for r in csv.DictReader(open(LOG, encoding="utf-8"))}


def ok_papers():
    return {pid: MD_DIR / (Path(r["filename"]).stem + ".md")
            for pid, r in read_log().items() if r["status"] == "ok"}


def sub_papers():
    """The pilot subsample. Falls back to all ok papers if no subsample yet."""
    allp = ok_papers()
    if not SUBSAMPLE.exists():
        return allp
    ids = {r["paper_id"] for r in csv.DictReader(open(SUBSAMPLE, encoding="utf-8"))}
    return {pid: p for pid, p in allp.items() if pid in ids}


def md_text(pid):
    p = ok_papers().get(pid)
    return p.read_text(encoding="utf-8") if p and p.exists() else ""


def trim_md(text):
    """Cheap deterministic trim: drop references/bibliography to the end of the
    doc UNLESS an appendix follows (appendices carry items). Conservative."""
    m = re.search(r'^#{0,3}\s*(references|bibliography|literatur|références)\s*$',
                  text, flags=re.I | re.M)
    if not m:
        return text
    tail = text[m.start():]
    a = re.search(r'^#{0,3}\s*(appendix|annex|supplementary)', tail, flags=re.I | re.M)
    if a:
        return text[:m.start()] + tail[a.start():]
    return text[:m.start()]


def banner(title):
    print(f"\n{'=' * 70}\n  {title}\n{'=' * 70}")


def restore_empty_sections(doc, a, b):
    """Guard against the judge zeroing out a whole top-level section. Under the
    non-strict adjudication schema the judge occasionally returns a record with
    empty `samples` or `pdf_quality` (or a blank `paper`), which would silently drop
    population/quality the CODERS actually captured. If a section is empty, restore
    it from the richer coder (most samples) so the judge can only correct a section,
    never delete it. Flags needs_human_review. Returns (doc, changed)."""
    cbase = None
    for d in (a, b):
        if d and (cbase is None or len(d.get("samples") or []) > len(cbase.get("samples") or [])):
            cbase = d
    if not cbase:
        return doc, False
    changed = False
    if not doc.get("samples") and (cbase.get("samples") or []):
        doc["samples"] = cbase["samples"]; changed = True
    if not (doc.get("pdf_quality") or {}) and (cbase.get("pdf_quality") or {}):
        doc["pdf_quality"] = cbase["pdf_quality"]; changed = True
    p = doc.get("paper") or {}
    if not (p.get("title") or p.get("study_type")) and (cbase.get("paper") or {}):
        doc["paper"] = cbase["paper"]; changed = True
    if changed:
        m = doc.setdefault("extraction_meta", {})
        m["needs_human_review"] = True
        note = (m.get("extraction_notes") or "")
        m["extraction_notes"] = (note + " | population/quality restored from coder "
                                 "(judge returned it empty)").strip(" |")
    return doc, changed


def merge_usage(path, new_rows, key):
    """Merge new_rows into the existing CSV at `path`, keyed by `key`. New
    rows win on conflict (a retry's result replaces the earlier failure for
    the same key). Without this, a retry's retrieve() would overwrite the
    whole ledger with just the retried subset, silently destroying the cost
    record for every paper retrieved before it."""
    existing = {}
    if path.exists():
        for r in csv.DictReader(open(path, encoding="utf-8")):
            existing[r[key]] = r
    for r in new_rows:
        existing[str(r[key])] = r
    return list(existing.values())
