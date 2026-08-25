Extract structured data from the paper below. The output format and all field-level rules are enforced by the schema — follow each field's description exactly.

**Copy what is printed in this document. Nothing else.**

## The evidence rule

You may recognise a published instrument and know its items. That knowledge is irrelevant here and you must not use it. If the text of an item is not printed in this document, it does not exist for your purposes. Every item you write is later string-matched against this document; text that is not found is discarded. A missed real item is recoverable later; an invented one silently corrupts the dataset — so when in doubt, leave it out.

## Work in this order

Do not start filling the schema top-to-bottom. First locate, then record. Follow these steps in order; each narrows the search for the next.

1. **Discover samples.** Scan Methods/Participants for every separately-analysed sample. Under-split, never over-split (see Judgment calls).
2. **Discover instruments.** List every NAMED multi-item instrument used, from the Measures section AND from correlation/validity tables and their footnotes (criterion instruments are often named only there). This is your scale list — do not add to it while extracting items, and do not drop one because its items aren't printed.
3. **For each instrument, anchor the evidence, then fill metadata.** Find the verbatim phrase that names it (`scale_evidence_quote`) first; extract `scale_name`, `scale_abbreviation`, `scale_citation`, `response_format`, `subscales` from around that anchor. A scale with no printed items still gets a full metadata row with `items_coverage: none` and `items: []`.
4. **For each instrument, hunt its printed items** using the ladder below. Do this per-scale, not as one sweep of the whole paper.
5. **Self-check** (see checklist), then emit JSON.

## The item-search ladder

For each scale, search these locations IN ORDER and stop at the first one that gives a complete printed item set:

Measures/Methods body → Appendix or Annex → factor-loading / rotated-component tables → translation or item-mapping tables → transcribed image/figure blocks ("Transcribed from image …") → item text quoted in correlation-table footnotes.

Pages are marked `<!-- page N -->`; use these for every `source_page`.

**A name, heading, or pointer is not the items.** These all mean the items are NOT present — set `items_coverage: none` and `items: []`:
- a heading like "Appendix II — Language Teacher Emotion Regulation Inventory" with no actual item lines beneath it in THIS text;
- a pointer such as `[tbl-9.md](tbl-9.md)`, "see Table 9", "see the supplementary material", or "items are listed in the appendix" — that content is NOT in this document;
- the scale's name, abbreviation, or citation appearing in the Measures section.

Only write an item when its full question/statement text is literally readable as a line in the text you were given.

## Items are not category names

An item is a full question or statement a participant answered. A category, dimension, or subscale NAME is not an item — those go in the scale's `subscales` field, never in `items`.

Worked examples:
- ✔ item: "How often do you feel that you lack companionship?"
- ✘ not an item (subscale name → `subscales`): "Neglect", "Physical Abuse", "Emotional Abuse"
- ✘ not an item (network metric): "number of friends", "size of social network"
- ✘ appendix heading with no lines beneath it → `items_coverage: none`, `items: []`
- ✘ a shared stem ("In the past week, how often did you…") is context, not an item → `shared_stem`, not `items`

## Self-check before emitting JSON

Confirm you actually visited each location for items — Measures, appendix, factor/loading tables, translation tables, image transcriptions, correlation-table footnotes. If you could not check one (e.g. OCR gap, truncated page), do not claim `full` coverage: set that scale to `sample` or `none` and lower `extraction_confidence` to `medium`, saying which location you couldn't verify in `confidence_reason`. Confidence should reflect what you were able to check, not how familiar the instrument is.

## Judgment calls

- Unsure whether something is a separate sample? Do NOT split. One object, `is_multi_population` true, rest in the note. Under-splitting is safe; over-splitting corrupts the data.
- Unsure whether an author-constructed measure counts as a scale? Include it if it is named or described and used as a measure, and say so in `extraction_notes`.
- Unsure about anything else? State it in `extraction_notes` rather than guessing. Say what is missing rather than hiding it.
