# One-time setup

    python3 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt

`00_ocr_v2.py` also needs `pdfinfo` from poppler (e.g. `brew install poppler`).

Create a .env file (same folder as this README) with:

    GEMINI_API_KEY=...
    OPENAI_API_KEY=...
    ANTHROPIC_API_KEY=...

If you already have OCR'd markdown, copy it in and skip step 00:

    cp -r /path/to/old/data/markdown data/markdown
    cp /path/to/old/data/papers_log.csv data/papers_log.csv

Every new terminal session:

    cd this-folder
    source .venv/bin/activate

Models are set in common.py:MODEL_ID — change them there, nowhere else.
