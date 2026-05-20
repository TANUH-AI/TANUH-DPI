"""
pypdf_engine.py -- Fast text extraction for digital PDFs using pypdf.

This is the fastest engine but only works on PDFs with embedded text
(not scanned/image PDFs). Used as the first attempt in the waterfall.
"""

from __future__ import annotations

import logging
from pathlib import Path

from nhcx_local.ocr_engines.normaliser import wrap_markdown

logger = logging.getLogger(__name__)

_ENGINE_NAME = "pypdf"


def run(pdf_path: Path, page_limit: int | None = None) -> str | None:
    """Extract text from a digital PDF using pypdf."""
    try:
        import pypdf
    except ImportError:
        logger.warning("pypdf not installed -- skipping.")
        return None

    try:
        reader = pypdf.PdfReader(str(pdf_path))
        pages_text = []
        total_text_len = 0

        for i, page in enumerate(reader.pages):
            if page_limit and i >= page_limit:
                break
            text = page.extract_text() or ""
            pages_text.append(text)
            total_text_len += len(text.strip())

        # If very little text, it's probably scanned -- return None to trigger fallback
        if total_text_len < max(1, len(pages_text)) * 50:
            return None

        return wrap_markdown(
            pages=pages_text,
            source_path=pdf_path,
            engine=_ENGINE_NAME,
            extra_meta={"fast_path": "true"},
        )
    except Exception as e:
        logger.warning(f"PyPDF extraction failed: {e}")
        return None
