"""
ocr.py -- Multi-engine OCR orchestrator for local use.

Waterfall: pypdf (fast) -> docling (high quality) -> fallback empty.

Public API:
    from nhcx_local.ocr import extract_pdf_to_markdown
    result = await extract_pdf_to_markdown(Path("claim.pdf"))
    print(result.markdown)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class OcrResult:
    """Result of OCR extraction."""
    markdown: str
    engine_used: str
    page_count: int
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any(
            line.strip()
            for line in self.markdown.splitlines()
            if not line.startswith(("---", "<!--", "source:", "engine:", "pages:", "extracted_at:"))
        )


async def extract_pdf_to_markdown(
    pdf_path: Path,
    page_limit: int | None = None,
) -> OcrResult:
    """
    Extract text from a PDF using a waterfall of OCR engines.
    Tries pypdf first (fast), then docling (high quality).
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    warnings: list[str] = []

    # Try pypdf first (instant, no GPU needed)
    from nhcx_local.ocr_engines.pypdf_engine import run as run_pypdf
    result = await asyncio.to_thread(run_pypdf, pdf_path, page_limit)
    if result:
        logger.info("OCR: pypdf succeeded for %s", pdf_path.name)
        return OcrResult(
            markdown=result,
            engine_used="pypdf",
            page_count=_count_pages(result),
            warnings=warnings,
        )
    warnings.append("pypdf: produced no output (likely scanned PDF) -- trying docling")

    # Try docling (higher quality, handles scanned PDFs)
    from nhcx_local.ocr_engines.docling_engine import run as run_docling
    result = await asyncio.to_thread(run_docling, pdf_path, page_limit)
    if result:
        logger.info("OCR: docling succeeded for %s", pdf_path.name)
        return OcrResult(
            markdown=result,
            engine_used="docling",
            page_count=_count_pages(result),
            warnings=warnings,
        )
    warnings.append("docling: produced no output")

    # All engines failed
    logger.error("All OCR engines failed for %s", pdf_path.name)
    from nhcx_local.ocr_engines.normaliser import wrap_markdown
    empty_md = wrap_markdown(
        pages=["*No text could be extracted from this PDF.*"],
        source_path=pdf_path,
        engine="none",
        extra_meta={"warning": "all_engines_failed"},
    )
    warnings.append("All engines produced empty output.")
    return OcrResult(
        markdown=empty_md,
        engine_used="none",
        page_count=0,
        warnings=warnings,
    )


def split_markdown_into_pages(markdown: str) -> list[str]:
    """Split combined markdown into per-page strings."""
    parts = re.split(r"<!--\s*PAGE\s+\d+\s*-->", markdown)
    return [p.strip() for p in parts[1:] if p.strip()]


def _count_pages(markdown: str) -> int:
    return len(re.findall(r"<!--\s*PAGE\s+\d+\s*-->", markdown))
