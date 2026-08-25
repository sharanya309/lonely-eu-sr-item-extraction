#!/usr/bin/env python3
"""
resolve.py — deterministic item resolution shared by steps 02 and 03.

No model calls:

  1. VERIFY: an extracted item is real only if its text actually appears in the
     paper markdown. Items that don't are dropped. This enforces the evidence
     rule in code instead of trusting the model — it's what catches a model
     "reconstructing" a famous instrument from memory (the single biggest
     source of coder disagreement we found).

  2. UNION: because every surviving item is proven to be in the source, an item
     found by EITHER coder is genuine. So the merged item set is the UNION of
     both coders' verified items (deduped by normalized text). This maximizes
     recall and makes item COUNT stop being a "disagreement" to adjudicate.

Everything here is deterministic and tested on real data.
"""
import json
from common import norm

_STOP = {"the", "a", "an", "of", "and", "for", "scale", "questionnaire", "index",
         "inventory", "measure", "items", "item", "scales", "version", "short",
         "form", "revised", "brief"}


def scale_key(sc):
    return norm(sc.get("scale_abbreviation")) or norm(sc.get("scale_name"))


def _tokens(sc):
    t = set()
    for f in ("scale_name", "scale_abbreviation"):
        t |= set(norm(sc.get(f)).replace("-", " ").split())
    return t - _STOP


def _sim(x, y):
    tx, ty = _tokens(x), _tokens(y)
    return len(tx & ty) / min(len(tx), len(ty)) if tx and ty else 0.0


def item_key(it):
    """Match items across coders on the ORIGINAL printed text. This is the stable
    join key because every verified item's original text is, by definition, present
    in the source — whereas item_text_english is an optional translation one coder
    may fill and another may leave blank. Keying on English (the old behaviour)
    made the SAME item look different across coders when translation differed,
    which both under-counted agreement (Jaccard) and double-counted the union.
    Falls back to English only if a coder left the original empty."""
    return norm(it.get("item_text_original") or it.get("item_text_english"))


def verified_items(sc, source_norm):
    """Only the items whose text is actually printed in this paper, deduped by
    normalized text. resolve_items' cross-coder union already dedupes via its own
    `seen` set, so this is a no-op there — but prune_record (used standalone on
    the judge's adjudicated output) has no other dedup, and the judge occasionally
    emits the same item twice (e.g. attributed to two subscales). Without this,
    that duplicate survives verification untouched and silently inflates the
    item count for that paper."""
    out, seen = [], set()
    for it in sc.get("items") or []:
        t = norm(it.get("item_text_original") or it.get("item_text_english"))
        if t and t in source_norm and t not in seen:
            seen.add(t)
            out.append(it)
    return out


def scale_in_source(sc, source_norm):
    """True if this scale is actually attested in the paper — its verbatim evidence
    quote, full name, or abbreviation appears in the source text. This mirrors the
    item verification for SCALES: a scale name a model produced that is nowhere in
    the paper (a hallucinated or mis-carried instrument) fails this check. The
    abbreviation is only trusted at length >= 3 to avoid spurious 1-2 char hits."""
    for f in ("scale_evidence_quote", "scale_name", "scale_abbreviation"):
        v = norm(sc.get(f))
        if len(v) >= 3 and v in source_norm:
            return True
    return False


def match_scales(sa, sb):
    """Pair scales across coders: exact key, then fuzzy token overlap. Returns
    (pairs, only_a, only_b)."""
    ib = {scale_key(s): s for s in sb}
    used, pairs, only_a = set(), [], []
    for s in sa:
        k = scale_key(s)
        m = ib.get(k)
        if m is None:
            cands = [(x, _sim(s, x)) for x in sb if scale_key(x) not in used]
            cands = [c for c in cands if c[1] >= 0.6]
            m = max(cands, key=lambda c: c[1])[0] if cands else None
        if m is not None and scale_key(m) not in used:
            pairs.append((s, m))
            used.add(scale_key(m))
        else:
            only_a.append(s)
    only_b = [s for s in sb if scale_key(s) not in used]
    return pairs, only_a, only_b


def _clean_scale(sc, items):
    """A scale with its verified/union item list and consistent count+coverage."""
    out = json.loads(json.dumps(sc))
    for it in items:
        it.pop("_verified", None)
    out["items"] = items
    out["items_extracted_count"] = len(items)
    if not items and out.get("items_coverage") != "none":
        out["items_coverage"] = "none"     # nothing printed here after verification
    return out


def _merge_subscales(scales):
    """Union the subscale names across every coder's copy of one scale, deduped
    case-insensitively and order-preserving. Fixes silent subscale loss: the old
    merge kept only the base coder's subscales, so a dimension found by the other
    coder(s) disappeared."""
    seen, out = set(), []
    for sc in scales:
        for part in (sc.get("subscales") or "").split(";"):
            p = part.strip()
            if p and p.lower() not in seen:
                seen.add(p.lower())
                out.append(p)
    return "; ".join(out)


def resolve_items(coder_docs, source_norm):
    """Merge N coder extractions into one scale list (N >= 1). Scales are clustered
    across coders (exact key first, then fuzzy token overlap); each cluster gets the
    UNION of every coder's source-verified items (deduped on original text) plus the
    UNION of subscale names, with the richest-metadata copy as the base. Because
    every surviving item is proven present in the source, unioning across ALL coders
    maximises recall without letting a fabricated item through.

    `coder_docs` is a list of extraction dicts (None entries are ignored), so it
    works for the two coders, a single coder, or any number of extractions.
    """
    docs = [d for d in coder_docs if d]
    clusters = []                              # each cluster = [scale-from-coder-i, ...]
    for d in docs:
        for sc in d.get("scales") or []:
            match = None
            k = scale_key(sc)
            if k:                              # 1) exact key wins over any fuzzy hit
                for cl in clusters:
                    if scale_key(cl[0]) == k:
                        match = cl
                        break
            if match is None:                  # 2) else first cluster over the fuzzy bar
                for cl in clusters:
                    if _sim(sc, cl[0]) >= 0.6:
                        match = cl
                        break
            if match is None:
                clusters.append([sc])          # new instrument
            else:
                match.append(sc)               # another coder's copy of a known one
    scales = []
    for cl in clusters:
        items, seen = [], set()
        for sc in cl:
            for it in verified_items(sc, source_norm):
                key = item_key(it)
                if key and key not in seen:
                    seen.add(key)
                    items.append(it)
        base = max(cl, key=lambda s: len(_tokens(s)))     # richest metadata as base
        merged = _clean_scale(base, items)
        subs = _merge_subscales(cl)
        if subs:
            merged["subscales"] = subs
        # Keep EVERY scale (a no-item scale is reported with items_coverage=none).
        # We don't drop anything — we just record whether the scale name is attested
        # in the source (name/abbreviation/evidence quote printed). This is a check
        # for review, not a filter, and mirrors the item verification.
        merged["scale_name_verified"] = any(scale_in_source(sc, source_norm) for sc in cl)
        scales.append(merged)
    return scales


def verified_item_set(doc, source_norm):
    """All verified item keys in a single extraction (for IRR/recall stats)."""
    keys = set()
    for sc in doc.get("scales") or []:
        for it in verified_items(sc, source_norm):
            k = item_key(it)
            if k:
                keys.add(k)
    return keys


def prune_record(doc, source_norm):
    """Drop unverifiable ITEMS from a single extraction (returns a new dict). Items
    not printed in the source are removed so no fabricated item can survive. SCALES
    are all KEPT — a scale with no printed items is reported with items_coverage=none
    — but each is flagged with `scale_name_verified` (whether its name/abbreviation/
    evidence quote is printed in the source), a check for review, not a filter. Used
    on the coder records shown to the judge and on the judge's own output."""
    out = json.loads(json.dumps(doc))
    for sc in out.get("scales") or []:
        sc_items = verified_items(sc, source_norm)
        for it in sc_items:
            it.pop("_verified", None)
        sc["items"] = sc_items
        sc["items_extracted_count"] = len(sc_items)
        if not sc_items and sc.get("items_coverage") != "none":
            sc["items_coverage"] = "none"
        sc["scale_name_verified"] = scale_in_source(sc, source_norm)
    return out
