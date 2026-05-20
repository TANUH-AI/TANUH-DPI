"""
docling_engine.py -- Docling OCR adapter (primary engine for local use).

Best for native digital PDFs with embedded text, rich structure,
tables, headings, multi-column layouts.

Install: pip install "docling>=2.0,<3"
"""

from __future__ import annotations

import logging
from pathlib import Path

from nhcx_local.ocr_engines.normaliser import wrap_markdown

logger = logging.getLogger(__name__)

_ENGINE_NAME = "docling"


def run(pdf_path: Path, page_limit: int | None = None) -> str | None:
    """Convert a PDF to structured Markdown using Docling."""
    try:
        from docling.document_converter import DocumentConverter
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
    except ImportError:
        logger.warning("docling not installed -- skipping. Install with: pip install 'docling>=2.0,<3'")
        return None

    try:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
        pipeline_options.do_table_structure = True

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

        result = converter.convert(str(pdf_path))
        doc = result.document

        total_pages = len(doc.pages)
        pages_to_process = list(doc.pages.keys())

        if page_limit:
            pages_to_process = pages_to_process[:page_limit]

        pages: list[str] = []
        for page_num in pages_to_process:
            try:
                page_md = doc.export_to_markdown(page_no=page_num)
                pages.append(page_md or "")
            except Exception as page_exc:
                logger.warning("Docling: failed to export page %d -- %s", page_num, page_exc)
                pages.append("")

        if not any(p.strip() for p in pages):
            logger.info("Docling: produced empty output for %s", pdf_path.name)
            return None

        logger.info("Docling: extracted %d/%d pages from %s", len(pages), total_pages, pdf_path.name)
        return wrap_markdown(pages=pages, source_path=pdf_path, engine=_ENGINE_NAME)

    except Exception as exc:
        logger.warning("Docling engine failed for %s: %s", pdf_path.name, exc)
        return None
