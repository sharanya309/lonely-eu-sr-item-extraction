#!/usr/bin/env python3
"""
=============================================================================
 01_extract_v2.py  —  EXACT COPY of 01_extract.py + ONE logged policy change.
 (originals are kept unmodified for reporting the previous runs.)

 v2 DECISION (2026-08-23): RETRY CAP so `auto` never gets stuck.
   In the original, a paper that always fails a coder (e.g. the ~3 Gemini
   papers last run) has no result file, so inputs() keeps returning it and
   `auto` RE-SUBMITS IT FOREVER. v2 caps attempts:
     - a per-coder counter data/coders/<coder>/attempts.json is incremented
       for every paper each time it is submitted,
     - after MAX_ATTEMPTS (=2) submissions with still no result, the paper is
       GIVEN UP: excluded from inputs(), so `auto` moves on and terminates,
     - given-up papers are logged to data/coders/<coder>/given_up.csv and via
       log_event("01_extract_v2", ...).
   Successful papers (result file present) are unaffected. Fully resumable;
   delete attempts.json for a coder to reset its counters.
   Change MAX_ATTEMPTS below to adjust.
=============================================================================

STEP 01 — extract, BATCH ONLY.

    python3 01_extract.py auto      [gemini|openai|both]   # Unattended: loops
                                                            # submit->poll->retrieve over
                                                            # every chunk.
    python3 01_extract.py submit    [gemini|openai|both]   # send one batch (manual)
    python3 01_extract.py status                            # poll progress
    python3 01_extract.py retrieve  [gemini|openai|both]    # pull results (manual)

Batch is asynchronous: submit, `status`; when a coder
shows "done", `retrieve` writes its results. Most batches finish well under an
hour (24h max). Everything is resumable — a paper already saved is never
re-fetched, and re-running submit won't resubmit an in-flight job.

Coder A = Gemini (MODEL_ID["gemini"]),  Coder B = OpenAI gpt-5.4 (reasoning model:
sent with reasoning_effort + max_completion_tokens, never temperature).
The two coders extract independently; disagreements are resolved by the judge
(step 03), which reads the paper and BOTH outputs and records the correct values.

Results (same paths the rest of the pipeline expects):
    data/coders/<coder>/results/<pid>.json
    data/coders/<coder>/job.json          batch id(s) + state
    data/coders/<coder>/usage.csv , failed.txt
"""
import csv
import json
import sys
import time
from pathlib import Path

import schema
from common import (CODERS, MODEL_ID, N_FULL, RATE, banner, load_env, log_event,
                    merge_usage, need, read_log, sub_papers, trim_md)

ROOT = Path(__file__).resolve().parent
PROMPT = (ROOT / "prompts" / "extract.md").read_text(encoding="utf-8").strip()

# v2 DECISION: give up on a (coder, paper) after this many submissions with no result.
MAX_ATTEMPTS = 2


def _attempts_path(coder):
    return CODERS / coder / "attempts.json"


def load_attempts(coder):
    p = _attempts_path(coder)
    return json.loads(p.read_text()) if p.exists() else {}


def save_attempts(coder, d):
    p = _attempts_path(coder)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2))


def _log_given_up(coder, entries):
    """Append (paper_id, filename, attempts) to given_up.csv, deduped by paper_id;
    log_event only for the newly given-up ones. entries = list of (pid, fn, n)."""
    if not entries:
        return
    gu = CODERS / coder / "given_up.csv"
    seen, rows = set(), []
    if gu.exists():
        for r in csv.DictReader(open(gu, encoding="utf-8")):
            seen.add(r["paper_id"]); rows.append(r)
    for pid, fn, n in entries:
        if pid not in seen:
            seen.add(pid)
            rows.append({"paper_id": pid, "filename": fn, "attempts": n})
            log_event("01_extract_v2",
                      f"{coder} GAVE UP on {pid} ({fn}) after {n} attempts (no result)")
    gu.parent.mkdir(parents=True, exist_ok=True)
    with open(gu, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["paper_id", "filename", "attempts"])
        w.writeheader(); w.writerows(rows)
MAX_OUT = {"gemini": 24000, "openai": 32000}
# Both providers cap the ENQUEUED TOKENS per batch (see your Batch API dashboard):
# Gemini 2.5 Flash = 3M, OpenAI gpt-5.4-mini = 2M. Submitting the whole corpus in one
# batch blows past this (207 multilingual papers >> 3M tokens -> 429 RESOURCE_EXHAUSTED).
# So each batch is bounded by BOTH a token budget (with margin) and a paper-count
# ceiling; the remainder is picked up by the next `submit` after retrieve (resumable).
MAX_BATCH = {"openai": 50, "gemini": 100}
TOKEN_BUDGET = {"gemini": 2_400_000, "openai": 1_600_000}   # safely under 3M / 2M


def cap_batch(coder, all_ins):
    """Prefix of all_ins that fits ONE batch: stop before the estimated enqueued
    tokens exceed the provider budget (or the paper-count ceiling). Estimate is
    conservative (~3 chars/token for dense multilingual text) so we stay under the
    hard limit. Always includes at least one paper. The rest resumes next submit."""
    budget = TOKEN_BUDGET.get(coder)
    picked, tok = [], 0
    for item in all_ins[:MAX_BATCH[coder]]:
        est = len(item[2]) // 3 + 600          # md chars/3 + prompt overhead
        if budget and picked and tok + est > budget:
            break
        picked.append(item)
        tok += est
    return picked


def user_msg(fn, md):
    return f"paper_id: {fn}\n\n<paper>\n{md}\n</paper>"


def inputs(coder):
    """Papers still needing this coder (skips ones already retrieved).
    v2: also skips papers GIVEN UP after MAX_ATTEMPTS submissions with no result,
    so `auto` can terminate instead of resubmitting a perma-failing paper forever."""
    done_dir = CODERS / coder / "results"
    done = {p.stem for p in done_dir.glob("*.json")} if done_dir.exists() else set()
    log = read_log()
    att = load_attempts(coder)                       # v2
    out, given_up = [], []                            # v2
    for pid, p in sorted(sub_papers().items()):
        if pid in done or not p.exists():
            continue
        if att.get(pid, 0) >= MAX_ATTEMPTS:           # v2: tried enough, still no result
            given_up.append((pid, log[pid]["filename"], att.get(pid, 0)))
            continue
        out.append((pid, log[pid]["filename"], trim_md(p.read_text(encoding="utf-8"))))
    _log_given_up(coder, given_up)                    # v2: record & log (deduped)
    return out


def body(coder, pid, fn, md):
    if coder == "gemini":
        model = MODEL_ID["gemini"]
        gcfg = {"responseMimeType": "application/json",
                "responseJsonSchema": schema.for_gemini(),
                "maxOutputTokens": MAX_OUT["gemini"]}
        if model.startswith("gemini-3"):
            gcfg["thinkingConfig"] = {"thinkingLevel": "low"}
        else:
            gcfg["temperature"] = 0
            # A small thinking budget lets Coder A run the discover->metadata->items
            # procedure in extract.md BEFORE it is locked into grammar-constrained JSON
            # (strict schema output leaves no room to plan otherwise). ~2k thinking
            # tokens/paper ~= $0.50 over the whole 200-paper corpus at batch rates.
            gcfg["thinkingConfig"] = {"thinkingBudget": 2048}
        return {"key": f"g_{pid}", "request": {
            "contents": [{"role": "user", "parts": [{"text": PROMPT},
                                                    {"text": user_msg(fn, md)}]}],
            "generationConfig": gcfg}}
    # OpenAI gpt-5.4 (reasoning): no temperature; max_completion_tokens + effort
    return {"custom_id": f"o_{pid}", "method": "POST", "url": "/v1/chat/completions",
            "body": {"model": MODEL_ID["openai"],
                     "messages": [{"role": "system", "content": PROMPT},
                                  {"role": "user", "content": user_msg(fn, md)}],
                     "response_format": schema.for_openai(),
                     "max_completion_tokens": MAX_OUT["openai"],
                     "reasoning_effort": "low"}}


def jpath(c):
    return CODERS / c / "job.json"


def jload(c):
    return json.loads(jpath(c).read_text()) if jpath(c).exists() else None


def jsave(c, d):
    jpath(c).parent.mkdir(parents=True, exist_ok=True)
    jpath(c).write_text(json.dumps(d, indent=2))


# --------------------------------------------------------------- submit
def submit(coder):
    if jload(coder):
        print(f"  [{coder}] a batch is already submitted — use status / retrieve.")
        return
    all_ins = inputs(coder)
    if not all_ins:
        print(f"  [{coder}] nothing to submit (all papers already have results).")
        return
    # Cap each batch under the provider's enqueued-token limit (token budget + count
    # ceiling); the remainder is picked up by the next `submit` after retrieve.
    ins = cap_batch(coder, all_ins)
    remaining = len(all_ins) - len(ins)
    # v2 DECISION: count one attempt per paper actually submitted in THIS batch.
    # After MAX_ATTEMPTS with no result, inputs() drops the paper (auto won't hang).
    att = load_attempts(coder)
    for pid, _, _ in ins:
        att[pid] = att.get(pid, 0) + 1
    save_attempts(coder, att)
    out = CODERS / coder
    out.mkdir(parents=True, exist_ok=True)
    jl = out / "batch_input.jsonl"
    with open(jl, "w", encoding="utf-8") as f:
        for pid, fn, md in ins:
            f.write(json.dumps(body(coder, pid, fn, md)) + "\n")
    tail = f" | {remaining} queued for next submit" if remaining else ""
    print(f"  [{coder}] {MODEL_ID[coder]} | submitting {len(ins)} papers{tail}")
    jid = _submit_gemini(jl) if coder == "gemini" else _submit_openai(jl)
    jsave(coder, {"job_id": jid, "n": len(ins)})
    print(f"  [{coder}] submitted: {jid}\n  Next: python3 01_extract.py status")
    log_event("01_extract", f"submit {coder} {MODEL_ID[coder]} n={len(ins)} "
                            f"queued={remaining} job={jid}")


def _submit_gemini(jl):
    from google import genai
    c = genai.Client(api_key=need("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    up = c.files.upload(file=str(jl), config={"mime_type": "application/jsonl"})
    for _ in range(60):                       # wait for file ACTIVE
        st = c.files.get(name=up.name).state
        if (st.name if hasattr(st, "name") else str(st)) == "ACTIVE":
            break
        time.sleep(3)
    return c.batches.create(model=MODEL_ID["gemini"], src=up.name,
                            config={"display_name": "extract"}).name


def _submit_openai(jl):
    from openai import OpenAI
    c = OpenAI(api_key=need("OPENAI_API_KEY"))
    up = c.files.create(file=open(jl, "rb"), purpose="batch")
    b = c.batches.create(input_file_id=up.id, endpoint="/v1/chat/completions",
                         completion_window="24h")
    if b.status == "failed":
        raise RuntimeError("; ".join(e.message for e in (b.errors.data if b.errors else []))
                           or "batch validation failed")
    return b.id


# --------------------------------------------------------------- status
def _state(coder):
    j = jload(coder)
    if not j:
        return "not submitted"
    jid = j["job_id"]
    if coder == "gemini":
        from google import genai
        c = genai.Client(api_key=need("GEMINI_API_KEY", "GOOGLE_API_KEY"))
        s = c.batches.get(name=jid).state
        s = s.name if hasattr(s, "name") else str(s)
        return "done" if "SUCCEEDED" in s else ("failed" if "FAILED" in s else "running")
    from openai import OpenAI
    s = str(OpenAI(api_key=need("OPENAI_API_KEY")).batches.retrieve(jid).status)
    return {"completed": "done", "failed": "failed", "expired": "failed",
            "cancelled": "failed"}.get(s, "running")


def _reason(coder):
    """Fetch the provider's batch-level failure reason (why the WHOLE job failed,
    as opposed to per-request errors). Free API call; never raises."""
    j = jload(coder)
    if not j:
        return ""
    jid = j["job_id"]
    try:
        if coder == "openai":
            from openai import OpenAI
            b = OpenAI(api_key=need("OPENAI_API_KEY")).batches.retrieve(jid)
            errs = getattr(b, "errors", None)
            data = getattr(errs, "data", None) if errs else None
            if data:
                return " | ".join(
                    f"{getattr(e, 'code', '') or ''}: {getattr(e, 'message', '') or ''}"
                    for e in data)
            return f"status={b.status}; request_counts={getattr(b, 'request_counts', None)}"
        from google import genai
        c = genai.Client(api_key=need("GEMINI_API_KEY", "GOOGLE_API_KEY"))
        b = c.batches.get(name=jid)
        return str(getattr(b, "error", "") or getattr(b, "state", ""))
    except Exception as e:
        return f"(could not fetch reason: {str(e)[:140]})"


def status():
    banner("01_extract status")
    total = len(sub_papers())
    for c in ("gemini", "openai"):
        j = jload(c)
        done = len(list((CODERS / c / "results").glob("*.json"))) \
            if (CODERS / c / "results").exists() else 0
        state = _state(c) if j else "not submitted"
        print(f"  [{c:6}] {MODEL_ID[c]:16} state={state:12} results {done}/{total}")
        if state == "failed":
            r = _reason(c)
            print(f"           reason: {r}")
            log_event("01_extract", f"{c} BATCH FAILED: {r}")
    print("\n  When a coder is 'done': python3 01_extract.py retrieve\n")


# --------------------------------------------------------------- retrieve
def save(coder, pid, text, ptok, otok, bad, rows, failed):
    d = CODERS / coder / "results"
    d.mkdir(parents=True, exist_ok=True)
    cost = ptok / 1e6 * RATE[coder]["in"] + otok / 1e6 * RATE[coder]["out"]
    st = "ok"
    if bad:
        st = "truncated"; failed.append(pid)
    else:
        try:
            doc = schema.add_counts(json.loads(text))
            (d / f"{pid}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
        except Exception as e:
            st = "invalid"; failed.append(pid)
            (d / f"{pid}.raw.txt").write_text(text or str(e), encoding="utf-8")
    rows.append({"paper_id": pid, "status": st, "in_tok": ptok, "out_tok": otok,
                 "cost_usd": round(cost, 5)})


def retrieve(coder):
    j = jload(coder)
    if not j:
        print(f"  [{coder}] nothing submitted.")
        return
    st = _state(coder)
    if st == "running":
        print(f"  [{coder}] not done yet (state=running). Check back later.")
        return
    if st == "failed":
        # cancelled / expired / validation-failed. A cancelled batch can still
        # have COMPLETED requests in its output file — pull them so paid-for work
        # isn't lost. A validation-failed batch has no output; handled gracefully.
        print(f"  [{coder}] state=failed/cancelled — reason: {_reason(coder)}")
        print(f"  [{coder}] pulling any COMPLETED requests so nothing paid-for is lost…")
    rows, failed = [], []
    (_get_gemini if coder == "gemini" else _get_openai)(j["job_id"], rows, failed)
    out = CODERS / coder
    merged = merge_usage(out / "usage.csv", rows, "paper_id")
    with open(out / "usage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["paper_id", "status", "in_tok", "out_tok", "cost_usd"])
        w.writeheader(); w.writerows(merged)
    ok = [r for r in merged if r["status"] == "ok"]
    still = [r["paper_id"] for r in merged if r["status"] != "ok"]
    (out / "failed.txt").write_text("\n".join(still))
    cost = sum(float(r["cost_usd"] or 0) for r in merged)
    per = cost / max(len(ok), 1)
    print(f"  [{coder}] ok {len(ok)} | failed {len(still)} | ${cost:.3f} "
          f"| ${per:.5f}/paper -> {N_FULL}: ~${per*N_FULL:.2f}")
    log_event("01_extract", f"retrieve {coder} {MODEL_ID[coder]} ok={len(ok)} "
                            f"failed={len(still)} cost=${cost:.3f}")
    jpath(coder).unlink(missing_ok=True)     # done -> clear so a re-submit sends any failures
    if still:
        print(f"  [{coder}] {len(still)} failed — just re-run `submit {coder}` to retry them.")


def _get_gemini(jid, rows, failed):
    from google import genai
    c = genai.Client(api_key=need("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    job = c.batches.get(name=jid)
    raw = c.files.download(file=job.dest.file_name).decode("utf-8")
    for ln in raw.strip().splitlines():
        if not ln.strip():
            continue
        rec = json.loads(ln)
        k = rec.get("key", "")
        pid = k[2:] if k.startswith("g_") else k
        resp = rec.get("response") or {}
        cands = resp.get("candidates")
        if not cands:
            rows.append({"paper_id": pid, "status": "failed", "in_tok": 0, "out_tok": 0, "cost_usd": 0})
            failed.append(pid); continue
        parts = (cands[0].get("content") or {}).get("parts") or []
        txt = next((p["text"] for p in parts if p.get("text")), "")
        trunc = cands[0].get("finishReason") == "MAX_TOKENS"
        um = resp.get("usageMetadata") or {}
        save("gemini", pid, txt,
             um.get("promptTokenCount", 0), um.get("candidatesTokenCount", 0), trunc,
             rows, failed)


def _get_openai(jid, rows, failed):
    from openai import OpenAI
    c = OpenAI(api_key=need("OPENAI_API_KEY"))
    b = c.batches.retrieve(jid)
    if not b.output_file_id:
        print("  [openai] no output file — requests errored.")
        if b.error_file_id:
            (CODERS / "openai" / "errors.jsonl").write_text(c.files.content(b.error_file_id).text)
            print("  [openai] see data/coders/openai/errors.jsonl")
        return
    raw = c.files.content(b.output_file_id).text
    for ln in raw.strip().splitlines():
        if not ln.strip():
            continue
        rec = json.loads(ln)
        cid = rec.get("custom_id", "")
        pid = cid[2:] if cid.startswith("o_") else cid
        resp = rec.get("response") or {}
        bd = resp.get("body")
        if rec.get("error") or not bd or resp.get("status_code") != 200:
            rows.append({"paper_id": pid, "status": "failed", "in_tok": 0, "out_tok": 0, "cost_usd": 0})
            failed.append(pid); continue
        ch = bd["choices"][0]
        bad = bool(ch["message"].get("refusal")) or ch.get("finish_reason") == "length"
        u = bd.get("usage", {})
        save("openai", pid, ch["message"].get("content") or "",
             u.get("prompt_tokens", 0), u.get("completion_tokens", 0), bad,
             rows, failed)


def cancel(coder):
    """Cancel an in-flight batch. Billing stops for anything still in progress;
    already-completed requests are billed but recoverable via `retrieve`."""
    j = jload(coder)
    if not j:
        print(f"  [{coder}] nothing to cancel."); return
    jid = j["job_id"]
    try:
        if coder == "openai":
            from openai import OpenAI
            OpenAI(api_key=need("OPENAI_API_KEY")).batches.cancel(jid)
        else:
            from google import genai
            genai.Client(api_key=need("GEMINI_API_KEY", "GOOGLE_API_KEY")).batches.cancel(name=jid)
        print(f"  [{coder}] cancel requested for {jid}.")
        print(f"  [{coder}] billed ONLY for completed requests. Wait ~1 min, then:")
        print(f"  [{coder}]   python3 01_extract.py retrieve {coder}   (saves whatever finished)")
        log_event("01_extract", f"cancel {coder} job={jid}")
    except Exception as e:
        print(f"  [{coder}] cancel failed: {str(e)[:160]}")


def auto(which="both", poll=60):
    """Unattended driver: loop submit -> poll -> retrieve across every chunk until
    all papers have results for the requested coder(s). Safe to leave running; safe
    to Ctrl-C and re-run (fully resumable). Picks up any batch already in flight."""
    coders = [c for c in ("gemini", "openai") if which in ("both", c)]
    total = len(sub_papers())
    banner("01_extract auto — submit/poll/retrieve on repeat, unattended")
    while True:
        # 1) submit the next chunk for any coder that is free and still has work
        for c in coders:
            if not jload(c) and inputs(c):
                try:
                    submit(c)
                except Exception as e:
                    print(f"  [{c}] submit failed: {type(e).__name__}: {str(e)[:200]}")
        inflight = [c for c in coders if jload(c)]
        if not inflight:
            if all(not inputs(c) for c in coders):
                # v2: report any papers given up after MAX_ATTEMPTS (logged in given_up.csv)
                for c in coders:
                    gu = CODERS / c / "given_up.csv"
                    ngu = (sum(1 for _ in csv.DictReader(open(gu, encoding="utf-8")))
                           if gu.exists() else 0)
                    if ngu:
                        print(f"  [{c}] gave up on {ngu} paper(s) after {MAX_ATTEMPTS} "
                              f"attempts -> {gu}")
                print(f"\n  Done: ALL PAPERS EXTRACTED ({', '.join(coders)}) "
                      f"[papers that kept failing were skipped after {MAX_ATTEMPTS} tries]. "
                      "Next: python3 02_agreement.py\n")
            else:
                print("\n  WARNING: Papers remain but no batch could be submitted "
                      "(quota/billing?). Fix it and re-run `auto`.\n")
            return
        # 2) poll the in-flight batches, retrieving each as it finishes
        while inflight:
            for c in list(inflight):
                try:
                    st = _state(c)
                except Exception as e:
                    print(f"  [{c}] status error: {str(e)[:120]}"); continue
                done = len(list((CODERS / c / "results").glob("*.json"))) \
                    if (CODERS / c / "results").exists() else 0
                print(f"  [{c:6}] {st:8}  {done}/{total} saved")
                if st in ("done", "failed"):
                    try:
                        retrieve(c)
                    except Exception as e:
                        print(f"  [{c}] retrieve error: {str(e)[:200]}")
                    inflight.remove(c)
            if inflight:
                time.sleep(poll)
        # loop back to submit the next chunks


def main():
    load_env()
    if len(sys.argv) < 2 or sys.argv[1] not in ("auto", "submit", "status", "retrieve", "cancel"):
        sys.exit(__doc__)
    act = sys.argv[1]
    which = (sys.argv[2] if len(sys.argv) > 2 else "both").lower()
    banner(f"01_extract {act}")
    if act == "status":
        status(); return
    if act == "auto":
        auto(which); return
    fn = {"submit": submit, "retrieve": retrieve, "cancel": cancel}[act]
    for c in ("gemini", "openai"):
        if which in ("both", c):
            try:
                fn(c)
            except Exception as e:
                # One provider's API error (quota/billing/network) must not abort the
                # other coder or dump a traceback. Report cleanly and carry on; the
                # step is resumable, so re-running submit retries only what's missing.
                msg = str(e).replace("\n", " ")
                print(f"  [{c}] {act} FAILED (provider error, not a code bug): {type(e).__name__}: {msg[:280]}")
                if "RESOURCE_EXHAUSTED" in msg or "429" in msg or "quota" in msg.lower():
                    print(f"  [{c}] -> this is a quota/billing limit on your {c} key. "
                          "Enable billing / raise your tier, then re-run this command.")
                log_event("01_extract", f"{c} {act} ERROR: {msg[:280]}")
    if act == "retrieve":
        print("\n  When both coders retrieved: python3 02_agreement.py\n")


if __name__ == "__main__":
    main()
