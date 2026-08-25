#!/usr/bin/env python3
"""
STEP 03 — adjudicate, BATCH ONLY (Anthropic Message Batches, 50% cheaper).

    python3 03_adjudicate.py auto        # Unattended: submit -> poll -> retrieve, THEN
                                          # runs 04_export automatically.
    python3 03_adjudicate.py submit      # send disagreeing papers to the judge (manual)
    python3 03_adjudicate.py status      # poll
    python3 03_adjudicate.py retrieve    # write final adjudicated records (manual)

Only papers that DISAGREED in step 02 (not already in data/final/auto/) are sent —
now including papers whose coders disagreed on scale/subscale/item content, not
just scalars. The judge returns the corrected record INCLUDING scales/subscales/
items; every item it returns is then re-verified against the source
(resolve.prune_record), so it can restructure/re-attribute items but never
reintroduce a fabricated one. If the judge truncates (or emits no scales), items
fall back to the two coders' verified union so nothing is lost. Resumable: papers
already in data/final/adjudicated/ are skipped.
"""
import csv
import json
import sys
from pathlib import Path

import resolve
import schema
from common import (CODERS, FINAL, MODEL_ID, RATE, banner, load_env, log_event,
                    md_text, merge_usage, need, norm, restore_empty_sections,
                    sub_papers, trim_md)

ROOT = Path(__file__).resolve().parent
ADJ_PROMPT = (ROOT / "prompts" / "adjudicate.md").read_text(encoding="utf-8").strip()
AUTO = FINAL / "auto"
ADJ = FINAL / "adjudicated"
JOB = FINAL / "adjudicate_job.json"
A, B = "gemini", "openai"


def rj(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


# enum fields -> their canonical value list (strict mode can drift on CASING only)
_ENUMS = {
    ("paper", "study_type"): schema.STUDY_TYPES,
    ("pdf_quality", "quality_flag"): schema.QUALITY,
    ("extraction_meta", "extraction_confidence"): schema.CONFIDENCE,
}
_SAMPLE_ENUMS = {"age_format": schema.AGE_FORMATS, "gender_format": schema.GENDER_FORMATS}
_SCALE_ENUMS = {"items_coverage": schema.COVERAGE}


def _canon(val, allowed):
    """Return the schema's canonical value for a case-insensitive match, else the
    original (strict mode guarantees the value is in-list except for capitalisation)."""
    if not isinstance(val, str):
        return val
    for a in allowed:
        if val.lower() == a.lower():
            return a
    return val


def normalize_enums(doc):
    for (parent, field), allowed in _ENUMS.items():
        p = doc.get(parent)
        if isinstance(p, dict) and field in p:
            p[field] = _canon(p[field], allowed)
    for s in doc.get("samples") or []:
        if isinstance(s, dict):
            for f, allowed in _SAMPLE_ENUMS.items():
                if f in s:
                    s[f] = _canon(s[f], allowed)
    for s in doc.get("scales") or []:
        if isinstance(s, dict):
            for f, allowed in _SCALE_ENUMS.items():
                if f in s:
                    s[f] = _canon(s[f], allowed)
    return doc


def coerce_adjudication(doc):
    """Anthropic tool use is FORCED (tool_choice) but not schema-ENFORCED the way
    OpenAI's strict json_schema is, so the judge occasionally drifts off-shape
    (e.g. collapsing extraction_meta into a bare string). Normalise the known
    drifts here so one off-shape field can't crash the whole retrieve."""
    if not isinstance(doc, dict):
        doc = {}
    m = doc.get("extraction_meta")
    if isinstance(m, str):                       # judge collapsed the object to a note
        m = {"extraction_notes": m}
    elif not isinstance(m, dict):
        m = {}
    m.setdefault("extraction_confidence", "medium")
    m.setdefault("confidence_reason", "")
    m.setdefault("extraction_notes", "")
    m.setdefault("needs_human_review", True)     # off-shape output -> flag for a human
    m.setdefault("overruled_summary", "")
    doc["extraction_meta"] = m
    for k in ("paper", "pdf_quality"):
        if not isinstance(doc.get(k), dict):
            doc[k] = {}
    for k in ("samples", "scales"):
        if not isinstance(doc.get(k), list):
            doc[k] = []
    return doc


def scale_item_table(a, b):
    def key(sc):
        return norm(sc.get("scale_name")) or norm(sc.get("scale_abbreviation"))
    ma = {key(s): len(s.get("items") or []) for s in (a.get("scales") or [])} if a else {}
    mb = {key(s): len(s.get("items") or []) for s in (b.get("scales") or [])} if b else {}
    rows = []
    for k in sorted(set(ma) | set(mb)):
        if not k:
            continue
        ca, cb = ma.get(k, "—"), mb.get(k, "—")
        rows.append(f"  {k[:60]:<60}  A={ca}  B={cb}{'' if ca == cb else '  <-- differs'}")
    return "\n".join(rows) or "  (no named scales)"


def brief(pid, a, b, fields):
    return "\n".join([f"paper_id: {pid}",
                      f"disagreeing fields flagged in step 02: {', '.join(fields) or 'none'}",
                      "", "Scale item-count comparison (A=gemini, B=openai):",
                      scale_item_table(a, b)])


def load_fields():
    f = FINAL / "disagreements.csv"
    if not f.exists():
        return {}
    return {r["paper_id"]: (r["fields"].split(";") if r["fields"] else [])
            for r in csv.DictReader(open(f, encoding="utf-8"))}


def judge_params(pid, a, b, source, fields):
    ns = norm(source)
    pa = resolve.prune_record(a, ns) if a else None
    pb = resolve.prune_record(b, ns) if b else None
    msg = "\n".join([
        "## Focused dispute brief (computed aid)\n" + brief(pid, pa, pb, fields),
        "\nNOTE: the items shown for each coder are already verified against the "
        "source (their printed text was found in the paper). Resolve the flagged "
        "SCALAR fields (study_type, total_n, age, gender, sample structure) AND the "
        "scale/subscale/item content: keep every printed item, attribute it to the "
        "right scale/subscale, drop anything not actually a questionnaire item, and "
        "set each scale's items_coverage. Every item you return is re-checked against "
        "the source afterwards, so include ONLY items whose text is printed here — "
        "never reconstruct an instrument from memory.",
        "\n## Coder A (gemini)\n" + (json.dumps(pa, ensure_ascii=False, indent=2) if pa else "MISSING"),
        "\n## Coder B (openai)\n" + (json.dumps(pb, ensure_ascii=False, indent=2) if pb else "MISSING"),
        "\n## Paper text (the only evidence)\n<paper>\n" + source + "\n</paper>"])
    # Full ADJUDICATION schema (WITH scales/items), non-strict: the nested items
    # array can't compile under strict grammar, and items are source-verified after
    # the judge responds anyway, so an off-shape or fabricated item can't survive.
    tool = schema.for_claude(schema.ADJUDICATION, name="emit_extraction", strict=False)
    # Haiku 4.5's standard output cap is 64k (docs: "standard limit 64k-128k"), so
    # 32000 is safe and well within it. The judge emits full records incl. items;
    # this headroom keeps item-heavy papers from truncating. If one still does, the
    # fallback in retrieve() reverts its items to the verified union (flagged).
    return {"model": MODEL_ID["judge"], "max_tokens": 32000, "system": ADJ_PROMPT,
            "tools": [tool], "tool_choice": {"type": "tool", "name": tool["name"]},
            "messages": [{"role": "user", "content": msg}]}


def todo():
    fields_by = load_fields()
    out = []
    for pid in sorted(sub_papers()):
        if (AUTO / f"{pid}.json").exists() or (ADJ / f"{pid}.json").exists():
            continue
        a, b = rj(CODERS / A / "results" / f"{pid}.json"), rj(CODERS / B / "results" / f"{pid}.json")
        if a is None and b is None:
            continue
        out.append((pid, a, b, fields_by.get(pid, [])))
    return out


def client():
    import anthropic
    return anthropic.Anthropic(api_key=need("ANTHROPIC_API_KEY"))


def submit():
    if JOB.exists():
        print("  a judge batch is already submitted — use status / retrieve.")
        return
    ADJ.mkdir(parents=True, exist_ok=True)
    items = todo()
    if not items:
        print("  nothing to adjudicate — all papers resolved.")
        return
    reqs = []
    for pid, a, b, fields in items:
        src = trim_md(md_text(pid))
        reqs.append({"custom_id": pid, "params": judge_params(pid, a, b, src, fields)})
    print(f"  judge {MODEL_ID['judge']} | submitting {len(reqs)} papers")
    batch = client().messages.batches.create(requests=reqs)
    JOB.write_text(json.dumps({"job_id": batch.id, "n": len(reqs)}, indent=2))
    print(f"  submitted: {batch.id}\n  Next: python3 03_adjudicate.py status")
    log_event("03_adjudicate", f"submit {MODEL_ID['judge']} n={len(reqs)} job={batch.id}")


def status():
    banner("03_adjudicate status")
    if not JOB.exists():
        print("  not submitted."); return
    jid = json.loads(JOB.read_text())["job_id"]
    b = client().messages.batches.retrieve(jid)
    done = len(list(ADJ.glob("*.json")))
    print(f"  batch {jid}: {b.processing_status} | counts={b.request_counts} | written {done}")
    print("\n  When 'ended': python3 03_adjudicate.py retrieve\n")


def retrieve():
    if not JOB.exists():
        print("  not submitted."); return
    jid = json.loads(JOB.read_text())["job_id"]
    c = client()
    b = c.messages.batches.retrieve(jid)
    if b.processing_status != "ended":
        print(f"  not done yet ({b.processing_status}). Try later."); return
    rows = []
    for entry in c.messages.batches.results(jid):
        pid = entry.custom_id
        if entry.result.type != "succeeded":
            err = getattr(entry.result, "error", None)
            print(f"    {pid}  {entry.result.type}  -> {str(err)[:400]}")
            continue
        msg = entry.result.message
        try:
            doc = next((blk.input for blk in msg.content if blk.type == "tool_use"), None)
            if doc is None:
                print(f"    {pid}  no tool_use"); continue
            trunc = getattr(msg, "stop_reason", None) == "max_tokens"
            doc = coerce_adjudication(doc)       # repair known judge drift before validating
            doc = normalize_enums(doc)           # fold enum values back to canonical casing
            a, b_ = rj(CODERS / A / "results" / f"{pid}.json"), rj(CODERS / B / "results" / f"{pid}.json")
            ns = norm(trim_md(md_text(pid)))
            # never let the judge DELETE a whole section (population/quality/paper) the
            # coders captured — restore any empty one from the richer coder.
            doc, _ = restore_empty_sections(doc, a, b_)
            # The judge resolved scales/items itself. Keep ONLY items whose text is
            # printed in the source (deterministic fabrication guard over the judge's
            # own output — it can restructure/attribute, but never invent). If the
            # judge truncated or returned no scales, fall back to the two coders'
            # verified union so no real item is silently lost.
            if trunc or not doc.get("scales"):
                doc["scales"] = resolve.resolve_items([a, b_], ns)
                doc["extraction_meta"]["needs_human_review"] = True
                if trunc:
                    doc["extraction_meta"]["extraction_notes"] = (
                        (doc["extraction_meta"].get("extraction_notes") or "")
                        + " | judge truncated: items fell back to verified union.").strip(" |")
            else:
                doc = resolve.prune_record(doc, ns)
            doc["provenance"] = "adjudicated"
            (ADJ / f"{pid}.json").write_text(json.dumps(schema.add_counts(doc), ensure_ascii=False, indent=2),
                                             encoding="utf-8")
        except Exception as e:
            # isolate failures: one bad paper is logged and skipped, never aborts the batch
            print(f"    {pid}  SKIPPED ({type(e).__name__}: {e})")
            continue
        u = msg.usage
        cost = (getattr(u, "input_tokens", 0) or 0) / 1e6 * RATE["judge"]["in"] + \
               (getattr(u, "output_tokens", 0) or 0) / 1e6 * RATE["judge"]["out"]
        rows.append({"paper_id": pid, "status": "ok",
                     "in_tok": getattr(u, "input_tokens", 0) or 0,
                     "out_tok": getattr(u, "output_tokens", 0) or 0, "cost_usd": round(cost, 5)})
    merged = merge_usage(FINAL / "adjudicate_usage.csv", rows, "paper_id")
    with open(FINAL / "adjudicate_usage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["paper_id", "status", "in_tok", "out_tok", "cost_usd"])
        w.writeheader(); w.writerows(merged)
    n_done = len(list(ADJ.glob("*.json")))
    if n_done >= json.loads(JOB.read_text()).get("n", 0):
        JOB.unlink(missing_ok=True)          # all resolved -> clear so a re-submit works
    else:
        print(f"    note: {n_done} of {json.loads(JOB.read_text()).get('n', 0)} written; "
              "job kept so you can re-run retrieve after fixing skips.")
    cost = sum(float(r["cost_usd"] or 0) for r in merged)
    print(f"  adjudicated {len(rows)} this run | cumulative {len(merged)} | ${cost:.3f}")
    log_event("03_adjudicate", f"retrieve adjudicated_this_run={len(rows)} "
                               f"cumulative={len(merged)} cost=${cost:.3f}")
    print("\n  Next: python3 04_export.py\n")


def auto(poll=60):
    """Unattended: submit the judge batch (if not already in flight), poll until it
    ends, retrieve, THEN run 04_export so you end with the final merged CSV of all
    records. Safe to Ctrl-C and re-run (resumable). If there is nothing to
    adjudicate (all papers already agreed), it goes straight to export."""
    import time
    import subprocess
    if not JOB.exists():
        try:
            submit()
        except Exception as e:
            print(f"  submit failed: {type(e).__name__}: {str(e)[:220]}")
            print("  (quota/billing? fix and re-run `auto`.) Exporting what exists so far…")
    while JOB.exists():
        try:
            ps = client().messages.batches.retrieve(json.loads(JOB.read_text())["job_id"]).processing_status
        except Exception as e:
            print(f"  status error: {str(e)[:140]}"); time.sleep(poll); continue
        done = len(list(ADJ.glob("*.json")))
        print(f"  judge: {ps}  ({done} adjudicated)")
        if ps == "ended":
            retrieve()
            break
        time.sleep(poll)
    # merge everything (adjudicated + auto-agreed + any coder-only fallback) -> final CSV
    print("\n  Merging all records and exporting the final CSV (04_export)…\n")
    subprocess.run([sys.executable, str(ROOT / "04_export.py")])
    print("\n  Cost ledger (optional): python3 05_costs.py\n")


def main():
    load_env()
    act = sys.argv[1] if len(sys.argv) > 1 else ""
    if act not in ("auto", "submit", "status", "retrieve"):
        sys.exit(__doc__)
    banner(f"03_adjudicate {act}")
    {"auto": auto, "submit": submit, "status": status, "retrieve": retrieve}[act]()


if __name__ == "__main__":
    main()
