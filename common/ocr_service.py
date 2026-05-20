"""
ocr_service.py — Multi-engine OCR orchestrator

Public API
----------
    from common.ocr_service import extract_pdf_to_markdown, OcrEngine, OcrResult

    result = await extract_pdf_to_markdown(
        pdf_path=Path("claim.pdf"),
        engine=OcrEngine.AUTO,
        language_hints=["en", "hi"],
        page_limit=10,
    )
    print(result.markdown)
    print(result.engine_used)

Engine selection
----------------
OcrEngine.AUTO  (default)
    Waterfall — tries each engine in priority order and returns the first
    non-empty result.  Order:  docling → lighton → surya → chandra

    Rationale:
    • Docling   — best quality for digital PDFs; try first
    • LightOn   — nearly as good, much faster; catches anything Docling misses
    • Surya     — transformer OCR for scanned/image PDFs
    • Chandra   — Tesseract; heavyweight last resort

OcrEngine.DOCLING / LIGHTON / SURYA / CHANDRA
    Force a specific engine; no fallback.

The function is async so it can be called from FastAPI route handlers
without blocking the event loop. The blocking OCR work runs inside
asyncio.to_thread().
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Engine modules are imported lazily inside _call_* functions below
# to prevent worker crashes when heavy transitive deps (torchvision, torch)
# are broken or absent in the CPU-only container.

logger = logging.getLogger(__name__)


# ── Public types ──────────────────────────────────────────────────────────────

class OcrEngine(str, Enum):
    AUTO     = "auto"
    PYPDF    = "pypdf"
    DOCLING  = "docling"
    LIGHTON  = "lighton"
    SURYA    = "surya"
    CHANDRA  = "chandra"
    CHANDRA2 = "chandra2"


@dataclass
class OcrResult:
    """Result of OCR extraction — always contains Markdown."""

    markdown: str
    """Full AI-ingestible Markdown with YAML front-matter and <!-- PAGE N --> markers."""

    engine_used: str
    """Name of the engine that produced the result (or 'none' if all failed)."""

    page_count: int
    """Number of pages extracted (from the front-matter)."""

    warnings: list[str] = field(default_factory=list)
    """Non-fatal warnings accumulated during extraction."""

    @property
    def is_empty(self) -> bool:
        """True when no text was extracted (only front-matter present)."""
        return not any(
            line.strip()
            for line in self.markdown.splitlines()
            if not line.startswith(("---", "<!--", "source:", "engine:", "pages:", "extracted_at:"))
        )


# ── Waterfall order ───────────────────────────────────────────────────────────
# Active engines: pypdf → docling → lighton
# Surya and Chandra are disabled because they require torch/transformers/tesseract
# which are not installed in the CPU-only worker environment.
# Re-enable by adding OcrEngine.SURYA / OcrEngine.CHANDRA below.

_WATERFALL: list[OcrEngine] = [
    OcrEngine.PYPDF,
    OcrEngine.DOCLING,
    OcrEngine.LIGHTON,
    # OcrEngine.SURYA,
    # OcrEngine.CHANDRA,
]


# ── Public entry point ────────────────────────────────────────────────────────

async def extract_pdf_to_markdown(
    pdf_path: Path,
    engine: OcrEngine = OcrEngine.AUTO,
    language_hints: list[str] | None = None,
    page_limit: int | None = None,
) -> OcrResult:
    """
    Extract text from a PDF and return structured Markdown.

    This is the single public function for all OCR operations.
    It runs the selected engine(s) in a thread pool so it is safe
    to await from an async FastAPI handler.

    Args:
        pdf_path:       Absolute path to the PDF file.
        engine:         Which engine to use. OcrEngine.AUTO enables waterfall.
        language_hints: ISO 639-1 language codes for OCR (e.g. ["en", "hi"]).
                        Ignored by Docling and LightOn (they are language-agnostic).
        page_limit:     Maximum pages to process. None means process all pages.

    Returns:
        OcrResult with .markdown, .engine_used, .page_count, .warnings.
    """
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    langs = language_hints or ["en"]
    warnings: list[str] = []

    if engine == OcrEngine.AUTO:
        markdown, engine_used = await _run_waterfall(
            pdf_path=pdf_path,
            langs=langs,
            page_limit=page_limit,
            warnings=warnings,
        )
    else:
        markdown = await _run_single_engine(
            engine=engine,
            pdf_path=pdf_path,
            langs=langs,
            page_limit=page_limit,
        )
        engine_used = engine.value

    if not markdown:
        logger.error("All OCR engines failed or produced no output for %s", pdf_path.name)
        markdown = _empty_result_markdown(pdf_path, engine_used or "none")
        warnings.append("All engines produced empty output — no text could be extracted.")
        engine_used = "none"

    page_count = _count_pages(markdown)

    return OcrResult(
        markdown=markdown,
        engine_used=engine_used,
        page_count=page_count,
        warnings=warnings,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _run_waterfall(
    pdf_path: Path,
    langs: list[str],
    page_limit: int | None,
    warnings: list[str],
) -> tuple[str | None, str]:
    """Try each engine in waterfall order; return first successful result."""
    for candidate in _WATERFALL:
        logger.info("OCR waterfall: trying %s for %s", candidate.value, pdf_path.name)
        result = await _run_single_engine(
            engine=candidate,
            pdf_path=pdf_path,
            langs=langs,
            page_limit=page_limit,
        )
        if result:
            logger.info("OCR waterfall: %s succeeded for %s", candidate.value, pdf_path.name)
            return result, candidate.value
        warnings.append(f"{candidate.value}: produced no output — trying next engine")

    return None, "none"


async def _run_single_engine(
    engine: OcrEngine,
    pdf_path: Path,
    langs: list[str],
    page_limit: int | None,
) -> str | None:
    """Dispatch to the correct engine module, always in a thread pool."""
    dispatch = {
        OcrEngine.PYPDF:    _call_pypdf,
        OcrEngine.DOCLING:  _call_docling,
        OcrEngine.LIGHTON:  _call_lighton,
        # OcrEngine.SURYA:    _call_surya,    # disabled — requires torch/transformers
        # OcrEngine.CHANDRA:  _call_chandra,  # disabled — requires tesseract
    }
    fn = dispatch.get(engine)
    if fn is None:
        logger.warning("Unknown OCR engine: %s", engine)
        return None

    return await asyncio.to_thread(fn, pdf_path, langs, page_limit)


def _call_pypdf(pdf_path: Path, langs: list[str], page_limit: int | None) -> str | None:
    import pypdf
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
            
        # Triage: if the PDF has very little text (e.g. < 50 chars per page on average), 
        # it's probably scanned or image-based. Return None to trigger fallback ML OCR.
        if total_text_len < max(1, len(pages_text)) * 50:
            return None

        from common.ocr_engines.normaliser import wrap_markdown
        return wrap_markdown(
            pages=pages_text,
            source_path=pdf_path,
            engine="pypdf",
            extra_meta={"fast_path": "true"}
        )
    except Exception as e:
        logger.warning(f"PyPDF extraction failed: {e}")
        return None


def _call_docling(pdf_path: Path, langs: list[str], page_limit: int | None) -> str | None:
    from common.ocr_engines import docling_engine
    return docling_engine.run(pdf_path=pdf_path, page_limit=page_limit)


def _call_lighton(pdf_path: Path, langs: list[str], page_limit: int | None) -> str | None:
    from common.ocr_engines import lighton_engine
    return lighton_engine.run(pdf_path=pdf_path, page_limit=page_limit)


# def _call_surya(pdf_path: Path, langs: list[str], page_limit: int | None) -> str | None:
#     return surya_engine.run(pdf_path=pdf_path, language_hints=langs, page_limit=page_limit)


# def _call_chandra(pdf_path: Path, langs: list[str], page_limit: int | None) -> str | None:
#     return chandra_engine.run(pdf_path=pdf_path, language_hints=langs, page_limit=page_limit)


def _count_pages(markdown: str) -> int:
    """Count <!-- PAGE N --> markers in the markdown to determine page count."""
    import re
    return len(re.findall(r"<!--\s*PAGE\s+\d+\s*-->", markdown))


def _empty_result_markdown(pdf_path: Path, engine: str) -> str:
    """Return a minimal valid Markdown when all engines fail."""
    from common.ocr_engines.normaliser import wrap_markdown
    return wrap_markdown(
        pages=["*No text could be extracted from this PDF.*"],
        source_path=pdf_path,
        engine=engine,
        extra_meta={"warning": "all_engines_failed"},
    )
def split_markdown_into_pages(markdown: str) -> list[str]:
    """Split the combined markdown into a list of per-page strings."""
    import re
    # Find all markers
    parts = re.split(r"<!--\s*PAGE\s+\d+\s*-->", markdown)
    # The first part is YAML front-matter; remaining are pages
    return [p.strip() for p in parts[1:] if p.strip()]
