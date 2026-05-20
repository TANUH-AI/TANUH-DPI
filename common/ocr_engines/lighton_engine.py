"""
lighton_engine.py — PyMuPDF4LLM adapter (LightOn engine)

Best for: fast text-layer extraction from digital PDFs with tables,
          multi-column layouts, and mixed content. Significantly lower
          latency than Docling for simple native PDFs.

PyMuPDF4LLM (Artifex) uses PyMuPDF's rendering engine to produce
LLM-optimised Markdown. It handles:
  - GFM table preservation
  - Header detection
  - Image references (captions)
  - Multi-column re-flow

Install: pip install "pymupdf4llm>=0.0.17" "pymupdf>=1.24"
"""

from __future__ import annotations

import logging
from pathlib import Path

from common.ocr_engines.normaliser import wrap_markdown

logger = logging.getLogger(__name__)

_ENGINE_NAME = "lighton"


def run(
    pdf_path: Path,
    page_limit: int | None = None,
) -> str | None:
    """
    Convert a PDF to Markdown using PyMuPDF4LLM (LightOn engine).

    Args:
        pdf_path:   Path to the PDF file.
        page_limit: If set, process only the first N pages (0-based list for pymupdf4llm).

    Returns:
        Markdown string on success, None if unavailable or output is empty.
    """
    try:
        import pymupdf4llm  # type: ignore[import]
        import fitz          # type: ignore[import]  # PyMuPDF
    except ImportError:
        logger.warning("pymupdf4llm not installed — skipping LightOn engine. "
                       "Install with: pip install 'pymupdf4llm>=0.0.17' 'pymupdf>=1.24'")
        return None

    try:
        # Determine page count so we can build a range
        with fitz.open(str(pdf_path)) as doc:
            total_pages = doc.page_count

        pages_to_process = list(range(total_pages))  # 0-based
        if page_limit:
            pages_to_process = pages_to_process[:page_limit]

        # pymupdf4llm returns one flat markdown string; we split per page
        # by running it page-by-page for consistent front-matter
        pages: list[str] = []
        for page_idx in pages_to_process:
            try:
                page_md = pymupdf4llm.to_markdown(str(pdf_path), pages=[page_idx])
                pages.append(page_md or "")
            except Exception as page_exc:
                logger.warning("LightOn: failed to process page %d — %s", page_idx + 1, page_exc)
                pages.append("")

        if not any(p.strip() for p in pages):
            logger.info("LightOn: produced empty output for %s", pdf_path.name)
            return None

        logger.info("LightOn: extracted %d/%d pages from %s",
                    len(pages_to_process), total_pages, pdf_path.name)

        return wrap_markdown(
            pages=pages,
            source_path=pdf_path,
            engine=_ENGINE_NAME,
        )

    except Exception as exc:
        logger.warning("LightOn engine failed for %s: %s", pdf_path.name, exc)
        return None
