#!/usr/bin/env python3
"""Single source of truth for the extraction schema, adapted per vendor.

v2: descriptions COMPRESSED for token cost (every request pays for them) while
keeping the disambiguating rules that prevent known errors (item-vs-subscale,
total_n=analyzed, no-fabrication, never-derive). item_text_english is now left
EMPTY when the original is already English, saving output tokens on English
papers. Field names, enums, vendor adapters and add_counts are UNCHANGED, so the
rest of the pipeline (01/02/03/04, resolve) is unaffected.
"""

NOT_PRINTED = '"" if not printed.'


def STR(desc=""):
    return {"type": "string", "description": (desc + " " + NOT_PRINTED).strip()}


def NUM(desc):
    return {"type": ["number", "null"],
            "description": desc + " null if absent; copy printed value, never derive."}


def INT(desc):
    return {"type": ["integer", "null"],
            "description": desc + " null if absent; copy printed value, never derive."}


def BOOL(desc):
    return {"type": "boolean", "description": desc}


def ENUM(vals, desc):
    return {"type": "string", "enum": vals, "description": desc}


def obj(props: dict, desc=None) -> dict:
    o = {"type": "object", "properties": props,
         "required": list(props.keys()), "additionalProperties": False}
    if desc:
        o["description"] = desc
    return o


def arr(item_schema: dict, desc=None) -> dict:
    a = {"type": "array", "items": item_schema}
    if desc:
        a["description"] = desc
    return a


AGE_FORMATS = ["mean_sd", "mean_only", "median", "range_only",
               "brackets", "mixed", "none"]
GENDER_FORMATS = ["pct", "counts", "pct_and_counts", "none"]
STUDY_TYPES = ["development", "validation", "both", "application"]
COVERAGE = ["full", "sample", "none"]
QUALITY = ["GOOD", "SCANNED", "POOR"]
CONFIDENCE = ["high", "medium", "low"]

PDF_QUALITY = obj({
    "text_extractable": BOOL("True if the document has usable extracted text."),
    "has_questionnaire_content": BOOL("True if any scale/item/questionnaire content appears."),
    "quality_flag": ENUM(QUALITY,
        "GOOD: readable, has scale content. SCANNED: image-based but legible. "
        "POOR: unreadable/cover-page-only, or a review/editorial/abstract with no "
        "sample and no scale (then samples=[], scales=[], say what it is in notes)."),
    "quality_notes": STR("Brief note on OCR gaps / missing pages / garbling."),
}, "Fill first.")

PAPER = obj({
    "paper_id": STR("The filename given to you."),
    "title": STR("Title as printed."),
    "year": INT("Publication year."),
    "language": STR("Paper language."),
    "country_study": STR("Country where the study was conducted."),
    "study_type": ENUM(STUDY_TYPES,
        "development=builds a NEW scale. validation=tests/validates/adapts/translates "
        "an EXISTING scale. both=develops AND validates a new scale. "
        "application=mainly uses existing scales to study another question."),
})

SAMPLE = obj({
    "sample_label": STR("Paper's own label, e.g. 'Study 1'."),
    "is_primary": BOOL("True for exactly one sample: the main analysed sample."),
    "is_multi_population": BOOL("True if this object stands in for several populations "
                               "you chose not to split. Under-splitting is safe."),
    "other_populations_note": STR("If multi-population, describe the others verbatim."),
    "total_n": INT("Participants ANALYZED (not recruited/invited). Never sum sub-samples "
                   "('Study 1 n=806, Study 2 n=74' -> primary is 806, not 880)."),
    "population_type": STR("Paper's own words, e.g. 'community-dwelling older adults'."),
    "country_location": STR("Country/location for THIS sample."),
    "age_mean": NUM("Mean age as printed."),
    "age_sd": NUM("SD of age as printed."),
    "age_range_min": NUM("Lower bound of a printed age range."),
    "age_range_max": NUM("Upper bound of a printed age range."),
    "age_notes": STR("Median/IQR, bracket distributions, other verbatim age oddities."),
    "age_format": ENUM(AGE_FORMATS,
        "How age is PRINTED. mean_sd=mean with SD. mean_only=mean, no SD. "
        "median=median/IQR (values in age_notes, numerics null). range_only='aged X-Y'. "
        "brackets=only a bracket distribution (in age_notes, numerics null). "
        "mixed=different participants in different formats. none=nothing printed."),
    "gender_pct_female": NUM("% female as printed."),
    "gender_n_female": INT("Count of female participants as printed."),
    "gender_pct_male": NUM("% male as printed."),
    "gender_n_male": INT("Count of male participants as printed."),
    "gender_pct_other": NUM("Sum of printed % for non-male/non-female categories."),
    "gender_n_other": INT("Sum of printed counts for non-male/non-female categories."),
    "gender_notes": STR("Name each non-male/female category; note if paper says 'sex' or 'gender'."),
    "gender_format": ENUM(GENDER_FORMATS,
        "pct=percentages only. counts=counts only. pct_and_counts=both. none=nothing. "
        "Fill only from printed values; NEVER derive % from n or n from %."),
}, "One object per SEPARATELY-analysed sample; most papers have one. If unsure, "
   "do NOT split: one object, is_multi_population=true, rest in other_populations_note. "
   "Copy age/gender exactly as printed; never convert between formats.")

ITEM = obj({
    "item_number": STR("Item's printed number/code."),
    "subscale": STR("Subscale/dimension as printed."),
    "item_text_original": STR("Exact printed item text (the question/statement a "
                              "participant answered), verbatim in its original language. "
                              "A category/dimension/subscale NAME is NOT an item (put "
                              "those in the scale's subscales field). String-matched to "
                              "the document; text not found there is discarded."),
    "item_text_english": {"type": "string",
        "description": "English translation. Leave EMPTY \"\" if item_text_original is "
                       "already English (do not duplicate it)."},
    "shared_stem": STR("Shared printed stem for sub-items, if any (the stem is not an item)."),
    "reverse_scored": BOOL("True only if the paper explicitly marks this item reverse-scored."),
    "source_page": INT("Page number ('<!-- page N -->') where the item text appears; "
                       "required when item_text_original is filled."),
})

SCALE = obj({
    "scale_name": STR("Full printed instrument name."),
    "scale_abbreviation": STR("Printed abbreviation, e.g. 'UCLA-LS'."),
    "scale_citation": STR("Citation the paper attaches, e.g. 'Russell, 1996'."),
    "which_sample": STR("Which sample_label this scale was administered to (or 'all')."),
    "scale_evidence_quote": STR("One verbatim phrase (<=25 words) naming this scale. Find it first."),
    "total_items_in_scale": INT("Item count the paper SAYS the instrument has."),
    "items_coverage": ENUM(COVERAGE,
        "full=complete item set printed here. sample=only some items printed. "
        "none=no item text printed here (items=[]). Items only in a supplement/online "
        "appendix count as none."),
    "response_format": STR("Printed response scale, e.g. '5-point Likert, 1=disagree..5=agree'."),
    "subscales": STR("Dimension/factor/subscale names separated by '; '. A multidimensional "
                     "scale is ONE entry with its dimensions here."),
    "items": arr(ITEM,
        "Only items whose text is PRINTED in this document. Do NOT reconstruct a known "
        "instrument from memory. Look in appendix, factor-loading tables, Measures, "
        "translation tables, and correlation/validity table footnotes."),
}, "One NAMED multi-item instrument = one entry. Include comparison/criterion instruments "
   "(check Measures AND correlation/validity tables + footnotes). Split into separate entries "
   "only if each part has its own name AND its own citation. Standalone single items go in one "
   "'Demographic/Contextual' entry. Exclude physical/clinical measurements (BMI, BP, labs) and "
   "computed network metrics.")

EXTRACT_META = obj({
    "extraction_confidence": ENUM(CONFIDENCE,
        "high=clear/complete. medium=ambiguity or OCR gaps. low=garbled, likely missed content."),
    "confidence_reason": STR("One sentence, required if medium/low."),
    "extraction_notes": STR("One short string: scales with no items printed, author-made "
                            "measures, multi-sample issues, anything uncertain."),
}, "Fill last.")

ADJUDICATE_META = obj({
    "extraction_confidence": ENUM(CONFIDENCE,
        "Confidence in this FINAL record. high=resolved cleanly vs text. medium=resolved on "
        "balance / OCR gaps. low=a material dispute unresolved from the text."),
    "confidence_reason": STR("One sentence, required if medium/low."),
    "extraction_notes": STR("One short string: scales with no items printed, author-made "
                            "measures, multi-sample issues, anything to re-check."),
    "needs_human_review": BOOL("True if <2 coders, a fabrication was deleted, a material "
                               "dispute was unresolved, or item text is doubtful."),
    "overruled_summary": STR("One short string: what you overruled and why."),
}, "Fill last. needs_human_review and overruled_summary exist only on the adjudicated record.")

EXTRACTION = obj({
    "pdf_quality": PDF_QUALITY,
    "paper": PAPER,
    "samples": arr(SAMPLE),
    "scales": arr(SCALE),
    "extraction_meta": EXTRACT_META,
}, "Copy what is printed in this document. Nothing else.")

ADJUDICATION = obj({
    "pdf_quality": PDF_QUALITY,
    "paper": PAPER,
    "samples": arr(SAMPLE),
    "scales": arr(SCALE),
    "extraction_meta": ADJUDICATE_META,
}, "The single final record for this paper.")

# Judge-only schema for STRICT structured output. Scales are OMITTED on purpose:
# the judge resolves scalar disputes only, and step 03 overwrites doc["scales"]
# with the deterministic verified-union AFTER the judge responds — so the judge
# never needs to emit scales/items (the nested item array is also what blows up
# the strict grammar). This keeps adjudication results identical while making the
# compiled grammar small enough to satisfy strict mode.
ADJUDICATION_STRICT = obj({
    "pdf_quality": PDF_QUALITY,
    "paper": PAPER,
    "samples": arr(SAMPLE),
    "extraction_meta": ADJUDICATE_META,
}, "Resolve the scalar fields only. Do NOT emit scales/items — they are resolved "
   "deterministically from the source after you respond.")


def for_openai(schema=EXTRACTION, name="extraction"):
    return {"type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema}}


def _gemini_clean(node):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k == "additionalProperties":
                continue
            if k == "type" and isinstance(v, list):
                out["type"] = [t for t in v if t != "null"][0]
                out["nullable"] = True
                continue
            out[k] = _gemini_clean(v)
        return out
    if isinstance(node, list):
        return [_gemini_clean(x) for x in node]
    return node


def for_gemini(schema=EXTRACTION):
    return _gemini_clean(schema)


def for_claude(schema=ADJUDICATION_STRICT, name="emit_extraction", strict=True):
    # strict=True -> grammar-constrained decoding guarantees the tool input matches
    # this schema (Anthropic structured outputs; supported on Haiku 4.5). Uses the
    # slim ADJUDICATION_STRICT schema (no scales/items) so the compiled grammar
    # stays small; scales are resolved deterministically downstream. All-required
    # (0 optional params), 12 nullable/union fields — within strict limits (24/16).
    #
    # strict=False is used by Coder C (01_extract), which needs the FULL EXTRACTION
    # schema *including* the nested items array. That array is too big to compile
    # under strict grammar, so Coder C runs unenforced: the tool schema guides the
    # model, and every item is still string-verified against the source downstream,
    # so an off-shape or fabricated item can never survive into the record.
    tool = {"name": name,
            "description": "Emit the structured extraction for this paper.",
            "input_schema": schema}
    if strict:
        tool["strict"] = True
    return tool


def add_counts(doc: dict) -> dict:
    """Validate top-level shape, then compute counts. Models drift from the
    schema; catch it here rather than three steps downstream."""
    if not isinstance(doc, dict):
        raise ValueError("root is not an object")
    for key, want in (("paper", dict), ("pdf_quality", dict), ("extraction_meta", dict),
                      ("samples", list), ("scales", list)):
        if key in doc and not isinstance(doc[key], want):
            raise ValueError(f"`{key}` is {type(doc[key]).__name__}, expected {want.__name__}")
    for key in ("samples", "scales"):
        for el in (doc.get(key) or []):
            if not isinstance(el, dict):
                raise ValueError(f"`{key}` contains a {type(el).__name__}, expected objects")
    for s in (doc.get("scales") or []):
        if not isinstance(s.get("items", []), list) or \
           any(not isinstance(i, dict) for i in (s.get("items") or [])):
            raise ValueError("`items` malformed")

    scales = doc.get("scales") or []
    for s in scales:
        s["items_extracted_count"] = len(s.get("items") or [])
    doc.setdefault("extraction_meta", {})
    doc["extraction_meta"]["total_scales_found"] = len(scales)
    doc["extraction_meta"]["total_items_extracted"] = sum(
        s["items_extracted_count"] for s in scales)
    return doc
