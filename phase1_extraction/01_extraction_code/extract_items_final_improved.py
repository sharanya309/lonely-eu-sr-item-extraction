"""
Social Connection Item Extractor
"""

import os
import time
import json
import pandas as pd
import PyPDF2
import google.generativeai as genai
from pathlib import Path
import re

# Config from R
try:
    API_KEY
except NameError:
    API_KEY = ""
try:
    INPUT_FILE
except NameError:
    INPUT_FILE = ""
try:
    OUTPUT_FILE
except NameError:
    OUTPUT_FILE = ""
try:
    RATE_LIMIT
except NameError:
    RATE_LIMIT = 14
try:
    CHECKPOINT_EVERY
except NameError:
    CHECKPOINT_EVERY = 25
try:
    RESUME
except NameError:
    RESUME = True
try:
    MAX_ARTICLES
except NameError:
    MAX_ARTICLES = None

# Extraction Prompt
EXTRACTION_PROMPT = """
You are extracting data from a SCALE DEVELOPMENT/VALIDATION paper about social connection.
THIS PAPER WILL CONTAIN A VALIDATED SCALE WITH ACTUAL ITEMS.

Extract BOTH population info AND measurement items.

PART A: POPULATION INFORMATION
Extract from Methods/Participants:
- Sample size (all studies if multiple: Study 1: N=200, Study 2: N=350)
- Population type and specific characteristics
- Age (M, SD, range), gender breakdown
- Country/location, recruitment method
- Clinical characteristics, exclusion criteria
- Copy 2-3 sentences describing sample verbatim

PART B: MEASUREMENT ITEMS - CRITICAL RULES

WHAT IS A MEASUREMENT ITEM?
The exact question or statement a participant saw and responded to.

CORRECT: "How often do you feel that you lack companionship?" | "I have someone I can turn to"
INCORRECT: "We measured loneliness" | "Social support was assessed"

WHERE TO FIND ITEMS:
1. Appendix/Supplementary (most common for formal scales)
2. Tables (factor loadings often list items)
3. Measures section (validated scales)
4. Results, Figures
5. **Demographics/Background section** - Structural items often here as standalone questions
6. **Methods - Contextual variables** - Structural measures not part of formal scales

CRITICAL FOR TRANSLATION/VALIDATION PAPERS:
If the paper contains translation tables (e.g., comparing English vs Dutch vs back-translation), the items in these tables ARE the actual scale items - extract them! Do not assume they are just examples. Papers validating translated questionnaires will show the items in table format for comparison.

IMPORTANT FOR STRUCTURAL ITEMS:
Structural items are often NOT part of formal scales. They may appear as:
- Single demographic questions (e.g., "Are you married?", "Do you live alone?")
- Background/contextual variables (e.g., "Number of close friends", "Frequency of contact with family")
- Social network questions scattered in Methods
- Living arrangement questions in sample description

Extract these even if they're NOT part of a named scale. Label scale_name as "Demographic questions" or "Contextual variables" if standalone.

EXTRACTION RULES:
1. VERBATIM: Copy exactly as written to "item_text_original"
2. TRANSLATE: If not English, translate to English for "item_text_english". If already English, copy the same text to both fields.
3. COMPLETE: Extract ALL items, not examples
4. RESPONSE FORMAT: Note scale (e.g., 5-point Likert)

CRITICAL TRANSLATION RULE:
- item_text_original: ALWAYS the text as it appears in the paper (Dutch, German, Spanish, etc.)
- item_text_english: ALWAYS translated to English (if original is English, duplicate it here)
- Never leave item_text_english empty - always provide English version

ITEM CLASSIFICATION:

STRUCTURAL: The connection to others via the existence of relationships and their roles (e.g., marital status, family size).
Measured quantitatively by assessing: size or diversity of social network, social group membership or participation, living arrangements, frequency of social interactions.

Examples (may appear as standalone questions OR in formal scales):
"How many close friends do you have?" | "Are you married?" | "Marital status: Single/Married/Divorced/Widowed" | "Do you live alone?" | "How many people in your household?" | "How many clubs/groups do you belong to?" | "How often do you see friends?" | "Times you contacted family in past month" | "Do you have children?" | "Number of siblings"

Common locations:
- Demographics section: marital status, living arrangements, family composition
- Background variables: network size, group membership
- Contextual measures: contact frequency, participation
- May be single standalone items, NOT part of a formal scale

FUNCTIONAL: A sense of connection that results from resources and functions provided or perceived to be available by social relationships (e.g., perceived social support, loneliness).
Measures assess whether support is received or perceived to be available to meet needs (emotional, physical, tangible, informational, belonging needs).

Examples:
"I have someone to talk to when upset" (emotional) | "Someone helps me with daily tasks" (physical/tangible) | "I can get good advice when needed" (informational) | "I have someone to do things with" (companionship) | "I feel part of a group" (belonging) | "Help would be available if needed" (perceived availability) | "How often do you feel isolated?" (loneliness) | "I feel left out" (loneliness) | "I lack companionship" (loneliness)

QUALITATIVE: The sense of connection to others based on positive and negative affective qualities (e.g., relationship satisfaction, intimacy, conflict).
Measures assess: relationship satisfaction, cohesion, intimacy, closeness, strain, conflict.

Examples:
"How satisfied are you with your relationships?" (satisfaction) | "I am happy with my marriage" (satisfaction) | "I feel close to my partner" (intimacy/closeness) | "I feel connected to others" (closeness) | "My family sticks together" (cohesion) | "We often argue" (conflict) | "My friends let me down" (strain) | "There is tension in my relationships" (strain) | "I can rely on my friends" (trust/quality) | "My relationships are good overall" (quality)

OUTPUT FORMAT:

{
  "article_metadata": {
    "title": "Full article title",
    "year": 2023,
    "language": "Language",
    "country_study": "Where study conducted",
    "study_type": "Scale development|Scale validation|Scale translation|Psychometric evaluation"
  },
  "population_info": {
    "total_sample_size": "N=XXX (list all if multiple studies)",
    "population_type": "General population|Students|Workers|Older adults|etc",
    "population_specific": "Specific description e.g. 'undergraduate psychology students'",
    "age_info": "M=XX.X, SD=X.X, range X-X",
    "gender_info": "XX% female, or N males/N females",
    "country_location": "Country and region",
    "recruitment_source": "How recruited",
    "clinical_characteristics": "None/Non-clinical or describe",
    "exclusion_criteria": "Who was excluded",
    "verbatim_sample_description": "EXACT 2-3 sentences from Methods describing sample",
    "population_confidence": "High|Medium|Low"
  },
  "scales_extracted": [
    {
      "scale_name": "Full scale name (or 'Demographic questions' for standalone structural items)",
      "scale_abbreviation": "Abbr (or empty for standalone items)",
      "scale_citation": "Original citation if mentioned",
      "scale_purpose": "What it measures",
      "item_source": "Full scale in paper|Subscale only|Appendix|Table|Supplementary|Demographics section|Methods",
      "total_items_in_scale": 12,
      "items_extracted": 12,
      "response_format": "5-point Likert (1=Strongly disagree to 5=Strongly agree) OR categorical OR numeric",
      "subscales": ["Family", "Friends"] or [] for standalone items,
      "items": [
        {
          "item_number": "1",
          "subscale": "Family (or empty for standalone items)",
          "item_text_original": "Exact text in original language (German/Spanish/Dutch/etc.)",
          "item_text_english": "English translation (if original is English, same text here)",
          "connection_type": "Functional|Qualitative|Structural",
          "domain": "Specific domain from lists above",
          "reverse_scored": false,
          "shared_stem": "The stem if items share one, else null",
          "extraction_confidence": "High|Medium|Low",
          "measures_social_connection": "YES|NO",
          "notes": "Any relevant notes"
        }
      ]
    }
  ],
  "scales_mentioned_not_extracted": [
    {
      "scale_name": "Scale that was ADMINISTERED but items not provided",
      "scale_abbreviation": "Abbr",
      "original_citation": "Citation",
      "num_items_reported": "20 items",
      "was_administered": true,
      "reason_not_extracted": "Items not in text|Only citation|In supplementary|Available upon request",
      "connection_type": "Functional|Qualitative|Structural|Unknown",
      "notes": "Any other relevant info"
    }
  ],
  "extraction_summary": {
    "total_scales_found": 1,
    "total_items_extracted": 12,
    "functional_items": 8,
    "qualitative_items": 4,
    "structural_items": 0,
    "extraction_completeness": "Complete|Partial|Minimal",
    "overall_confidence": "High|Medium|Low",
    "needs_review": false,
    "review_reason": null,
    "extraction_notes": "Any issues"
  }
}

QUALITY STANDARDS:
High confidence: All items explicit, verbatim wording, clear response format
Medium confidence: Some items paraphrased, response format inferred
Low confidence: Many items missing, significant inference

CRITICAL: Extract EVERY item. If scale has 38 items, extract all 38.
Search entire text: Methods, Results, Tables, Appendix.

CRITICAL FOR STRUCTURAL ITEMS: 
Look in Demographics, Background, and Methods sections for standalone structural questions.
These are often NOT part of a formal scale but are single items asking about:
- Marital status, living arrangements, number of children
- Network size, frequency of contact with family/friends
- Group memberships, social participation
Extract these as a separate "scale" with scale_name = "Demographic questions" or "Contextual variables".

NOW ANALYZE THIS ARTICLE:

{text}

Respond ONLY with valid JSON (no markdown, no extra text).
"""

GEMINI_MODEL = None

def init_gemini():
    global GEMINI_MODEL
    genai.configure(api_key=API_KEY)
    
    # Try models in order - prioritize ones that work with current quota
    model_priority = [
        "models/gemini-2.0-flash",      # preferred
        "models/gemini-2.0-flash-001",  # alternate
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash",
        "models/gemini-2.0-flash-exp"
    ]
    
    for model_name in model_priority:
        try:
            model = genai.GenerativeModel(model_name)
            model.generate_content("Test")
            GEMINI_MODEL = model
            print(f"Using {model_name}")
            return model_name
        except Exception as e:
            continue
    
    # Last resort fallback
    print("WARNING: Gemini 2.0 Flash not available, trying any available model...")
    try:
        available = [m.name for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
        if available:
            model = genai.GenerativeModel(available[0])
            model.generate_content("Test")
            GEMINI_MODEL = model
            print(f"Using fallback: {available[0]}")
            return available[0]
    except Exception as e:
        print(f"All models failed: {str(e)[:100]}")
    
    return None


def extract_pdf_text(pdf_path):
    try:
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = '\n'.join(page.extract_text() for page in reader.pages)
            return (text, 'READY') if len(text.strip()) > 200 else (None, 'NOT_READABLE')
    except:
        return (None, 'ERROR')

def fix_json_string(text):
    """Aggressively fix common JSON issues"""
    # Remove markdown code blocks
    text = re.sub(r'^```json?\s*\n?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\n?\s*```$', '', text)
    
    # Remove any text before first { and after last }
    if '{' in text:
        text = text[text.find('{'):]
    if '}' in text:
        text = text[:text.rfind('}')+1]
    
    # Fix trailing commas
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    
    # Fix missing commas between objects/arrays
    text = re.sub(r'}\s*{', '},{', text)
    text = re.sub(r']\s*\[', '],[', text)
    
    # Remove control characters but keep newlines/tabs
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')
    
    # Fix smart quotes
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace(''', "'").replace(''', "'")
    
    return text.strip()

def extract_with_gemini(text):
    if not GEMINI_MODEL:
        return {'extraction_status': 'api_error'}
    
    prompt = EXTRACTION_PROMPT.replace('{text}', text[:100000])
    
    # Try 5 times with gradually increasing temperature
    for attempt in range(5):
        temp = 0.1 + (attempt * 0.1)  # 0.1, 0.2, 0.3, 0.4, 0.5
        try:
            response = GEMINI_MODEL.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temp,
                    top_p=0.95,
                )
            )
            if not response or not response.text:
                time.sleep(1)
                continue
            
            # Clean and parse JSON
            result_text = fix_json_string(response.text)
            result = json.loads(result_text)
            result['extraction_status'] = 'success'
            return result
            
        except json.JSONDecodeError:
            # Try to extract at least the items array
            try:
                if '"items"' in result_text and '[' in result_text:
                    items_match = re.search(r'"items"\s*:\s*\[(.*?)\](?=\s*[},])', result_text, re.DOTALL)
                    if items_match:
                        items_json = '[' + items_match.group(1) + ']'
                        items = json.loads(items_json)
                        # Return minimal valid structure with extracted items
                        return {
                            'extraction_status': 'success',
                            'article_metadata': {},
                            'population_info': {},
                            'scales_extracted': [{
                                'scale_name': 'Extracted scale',
                                'items': items,
                                'total_items_in_scale': len(items),
                                'items_extracted': len(items)
                            }],
                            'extraction_summary': {
                                'total_items_extracted': len(items),
                                'total_scales_found': 1
                            }
                        }
            except:
                pass
            
            if attempt < 4:
                time.sleep(1)
                continue
            return {'extraction_status': 'json_error'}
            
        except Exception as e:
            if attempt < 4:
                time.sleep(1)
                continue
            return {'extraction_status': 'api_error', 'error': str(e)[:200]}
    
    return {'extraction_status': 'failed'}

def result_to_rows(result, filename):
    rows = []
    
    meta = result.get('article_metadata', {})
    pop = result.get('population_info', {})
    summary = result.get('extraction_summary', {})
    
    # Metadata columns
    base_row = {
        'doi': '',
        'url': '',
        'title': meta.get('title', ''),
        'year': meta.get('year', ''),
        'language': meta.get('language', ''),
        'country_study': meta.get('country_study', ''),
        'study_type': meta.get('study_type', ''),
        'filename': filename,
        'extraction_status': result.get('extraction_status', ''),
        'quality_flags': '',
        'notes': '',
        'total_sample_size': pop.get('total_sample_size', ''),
        'population_type': pop.get('population_type', ''),
        'population_specific': pop.get('population_specific', ''),
        'age_info': pop.get('age_info', ''),
        'gender_info': pop.get('gender_info', ''),
        'country_location': pop.get('country_location', ''),
        'recruitment_source': pop.get('recruitment_source', ''),
        'clinical_characteristics': pop.get('clinical_characteristics', ''),
        'exclusion_criteria': pop.get('exclusion_criteria', ''),
        'verbatim_sample_description': pop.get('verbatim_sample_description', ''),
        'population_confidence': pop.get('population_confidence', ''),
        'scale_name': '',
        'scale_abbreviation': '',
        'scale_citation': '',
        'scale_purpose': '',
        'item_source': '',
        'total_items_in_scale': '',
        'items_extracted_count': '',
        'response_format': '',
        'subscales': '',
        'was_administered': '',
        'item_number': '',
        'subscale': '',
        'item_text_original': '',
        'item_text_english': '',
        'connection_type': '',
        'domain': '',
        'reverse_scored': '',
        'shared_stem': '',
        'extraction_confidence': '',
        'measures_social_connection': '',
        'item_notes': '',
        'total_scales_found': summary.get('total_scales_found', 0),
        'total_items_extracted': summary.get('total_items_extracted', 0),
        'needs_review': summary.get('needs_review', False),
        'review_reason': summary.get('review_reason', '')
    }
    
    # Handle extraction failures
    if result.get('extraction_status') != 'success':
        base_row['needs_review'] = True
        return [base_row]
    
    # Check if needs review
    n_items = summary.get('total_items_extracted', 0)
    confidence = summary.get('overall_confidence', '').lower()
    
    if n_items == 0 or confidence == 'low':
        base_row['needs_review'] = True
    
    scales = result.get('scales_extracted', [])
    
    if not scales:
        base_row['needs_review'] = True
        return [base_row]
    
    for scale in scales:
        scale_row = base_row.copy()
        scale_row['scale_name'] = scale.get('scale_name', '')
        scale_row['scale_abbreviation'] = scale.get('scale_abbreviation', '')
        scale_row['scale_citation'] = scale.get('scale_citation', '')
        scale_row['scale_purpose'] = scale.get('scale_purpose', '')
        scale_row['item_source'] = scale.get('item_source', '')
        scale_row['total_items_in_scale'] = scale.get('total_items_in_scale', '')
        scale_row['items_extracted_count'] = scale.get('items_extracted', '')
        scale_row['response_format'] = scale.get('response_format', '')
        scale_row['subscales'] = '; '.join(scale.get('subscales') or []) if scale.get('subscales') else ''
        
        items = scale.get('items', [])
        
        if not items:
            scale_row['needs_review'] = True
            rows.append(scale_row)
        else:
            for item in items:
                item_row = scale_row.copy()
                item_row['item_number'] = item.get('item_number', '')
                item_row['subscale'] = item.get('subscale', '')
                item_row['item_text_original'] = item.get('item_text_original', '')
                item_row['item_text_english'] = item.get('item_text_english', '')
                item_row['connection_type'] = item.get('connection_type', '')
                item_row['domain'] = item.get('domain', '')
                item_row['reverse_scored'] = item.get('reverse_scored', '')
                item_row['shared_stem'] = item.get('shared_stem', '')
                item_row['extraction_confidence'] = item.get('extraction_confidence', '')
                item_row['measures_social_connection'] = item.get('measures_social_connection', '')
                item_row['item_notes'] = item.get('notes', '')
                rows.append(item_row)
    
    # Add scales mentioned but not extracted
    not_extracted = result.get('scales_mentioned_not_extracted', [])
    for scale in not_extracted:
        if not scale.get('was_administered', True):
            continue
        row = base_row.copy()
        row['scale_name'] = scale.get('scale_name', '')
        row['scale_abbreviation'] = scale.get('scale_abbreviation', '')
        row['scale_citation'] = scale.get('original_citation', '')
        row['total_items_in_scale'] = scale.get('num_items_reported', '')
        row['connection_type'] = scale.get('connection_type', '')
        row['item_source'] = scale.get('reason_not_extracted', '')
        row['was_administered'] = True
        row['needs_review'] = True
        row['review_reason'] = scale.get('reason_not_extracted', '')
        rows.append(row)
    
    return rows

def main():
    if not API_KEY:
        print("Error: API_KEY not set")
        return
    
    print("Initializing Gemini...")
    model = init_gemini()
    if not model:
        print("Error: Could not initialize Gemini")
        return
    print(f"Using {model}")
    
    df_input = pd.read_csv(INPUT_FILE) if INPUT_FILE.endswith('.csv') else pd.read_excel(INPUT_FILE)
    
    if 'filepath' not in df_input.columns:
        print("Error: 'filepath' column required")
        return
    
    if MAX_ARTICLES:
        df_input = df_input.head(MAX_ARTICLES)
        print(f"Processing {len(df_input)} PDFs (limited to MAX_ARTICLES={MAX_ARTICLES})")
    else:
        print(f"Processing {len(df_input)} PDFs")
    
    checkpoint_file = OUTPUT_FILE.replace('.xlsx', '.checkpoint.xlsx')
    processed_file = OUTPUT_FILE.replace('.xlsx', '.processed.txt')
    
    processed = set()
    all_rows = []
    
    if RESUME and os.path.exists(processed_file):
        with open(processed_file, 'r') as f:
            processed = set(f.read().splitlines())
        if os.path.exists(checkpoint_file):
            all_rows = pd.read_excel(checkpoint_file).to_dict('records')
        print(f"Resuming: {len(processed)} processed")
    
    delay = 60 / RATE_LIMIT
    start = time.time()
    
    for i, row in df_input.iterrows():
        filepath = row['filepath']
        filename = Path(filepath).name
        
        if filename in processed:
            continue
        
        print(f"[{i+1}/{len(df_input)}] {filename[:50]}...", end=' ')
        
        text, ocr_status = extract_pdf_text(filepath)
        
        if not text:
            print(f"OCR: {ocr_status}")
            row = {
                'filename': filename,
                'extraction_status': 'not_readable',
                'quality_flags': 'NOT_READABLE' if ocr_status == 'NOT_READABLE' else 'PDF_ERROR',
                'notes': f'PDF not readable: {ocr_status}'
            }
            all_rows.append(row)
            processed.add(filename)
            continue
        
        result = extract_with_gemini(text)
        rows = result_to_rows(result, filename)
        all_rows.extend(rows)
        processed.add(filename)
        
        if result.get('extraction_status') == 'success':
            n = sum(len(s.get('items', [])) for s in result.get('scales_extracted', []))
            print(f"OK: {n} items")
        else:
            print(f"FAIL: {result.get('extraction_status')}")
        
        if (i + 1) % CHECKPOINT_EVERY == 0:
            pd.DataFrame(all_rows).to_excel(checkpoint_file, index=False)
            with open(processed_file, 'w') as f:
                f.write('\n'.join(processed))
        
        time.sleep(delay)
    
    pd.DataFrame(all_rows).to_excel(OUTPUT_FILE, index=False)
    
    if os.path.exists(checkpoint_file):
        os.remove(checkpoint_file)
    if os.path.exists(processed_file):
        os.remove(processed_file)
    
    elapsed = (time.time() - start) / 60
    n_success = sum(1 for r in all_rows if r.get('extraction_status') == 'success')
    print(f"\nComplete: {elapsed:.1f} min, {n_success} successful")

if __name__ == "__main__":
    main()
