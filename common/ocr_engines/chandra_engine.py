"""
chandra_engine.py — Pytesseract (Tesseract) adapter (Chandra engine)

Best for: heavyweight fallback when all other engines produce empty output.
          Tesseract is the industry-standard open-source OCR engine with
          150+ language packs and excellent accuracy on clean scans at ≥300 DPI.

Prerequisites (OS-level):
  macOS:   brew install tesseract tesseract-lang
  Ubuntu:  sudo apt install tesseract-ocr tesseract-ocr-hin (etc.)
  Docker:  RUN apt-get install -y tesseract-ocr

Python:    pip install "pytesseract>=0.3.10" "Pillow>=10.0" "pymupdf>=1.24"

Language hint format: ISO 639-3 codes separated by '+' (e.g. "eng+hin").
We accept ISO 639-1 codes (e.g. "en", "hi") and map them automatically.
"""

from __future__ import annotations

import logging
from pathlib import Path

from common.ocr_engines.normaliser import wrap_markdown

logger = logging.getLogger(__name__)

_ENGINE_NAME = "chandra"

# ISO 639-1 → Tesseract language pack mapping (common Indian + global)
_LANG_MAP: dict[str, str] = {
    "en": "eng", "hi": "hin", "ta": "tam", "te": "tel",
    "kn": "kan", "ml": "mal", "mr": "mar", "gu": "guj",
    "pa": "pan", "bn": "ben", "or": "ori", "ur": "urd",
    "fr": "fra", "de": "deu", "es": "spa", "zh": "chi_sim",
    "ar": "ara", "ja": "jpn", "ko": "kor",
}


def _to_tesseract_langs(hints: list[str]) -> str:
    """Convert ISO 639-1 hints to tesseract '+'-separated lang string."""
    mapped = [_LANG_MAP.get(h.lower(), h) for h in hints]
    # deduplicate while preserving order
    seen: set[str] = set()
    unique = [x for x in mapped if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]
    return "+".join(unique) if unique else "eng"


def _check_tesseract() -> bool:
    """Return True if tesseract binary is available on PATH."""
    try:
        import pytesseract  # type: ignore[import]
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def run(
    pdf_path: Path,
    language_hints: list[str] | None = None,
    page_limit: int | None = None,
    dpi: int = 300,
) -> str | None:
    """
    Convert a PDF to Markdown using Tesseract OCR (Chandra engine).

    Args:
        pdf_path:       Path to the PDF file.
        language_hints: ISO 639-1 language codes (e.g. ["en", "hi"]).
        page_limit:     If set, process only the first N pages.
        dpi:            Render resolution. ≥300 DPI recommended for accuracy.

    Returns:
        Markdown string on success, None if unavailable or output is empty.
    """
    try:
        import pytesseract        # type: ignore[import]
        from PIL import Image     # type: ignore[import]
        import fitz               # type: ignore[import]
    except ImportError:
        logger.warning("pytesseract/Pillow/pymupdf not installed — skipping Chandra engine. "
                       "Install with: pip install 'pytesseract>=0.3.10' 'Pillow>=10.0'")
        return None

    if not _check_tesseract():
        logger.warning(
            "Tesseract binary not found — skipping Chandra engine. "
            "Install with: brew install tesseract  (macOS)  or  "
            "sudo apt install tesseract-ocr  (Ubuntu)"
        )
        return None

    langs = _to_tesseract_langs(language_hints or ["en"])
    zoom = dpi / 72.0  # PyMuPDF default is 72 DPI
    mat = fitz.Matrix(zoom, zoom)

    try:
        pages: list[str] = []
        confidences: list[float] = []

        with fitz.open(str(pdf_path)) as doc:
            total_pages = doc.page_count
            page_indices = list(range(total_pages))
            if page_limit:
                page_indices = page_indices[:page_limit]

            for page_idx in page_indices:
                try:
                    page = doc[page_idx]
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                    # Run Tesseract
                    page_text = pytesseract.image_to_string(img, lang=langs)

                    # Get per-word confidence data
                    try:
                        data = pytesseract.image_to_data(
                            img, lang=langs,
                            output_type=pytesseract.Output.DICT
                        )
                        word_confs = [
                            c / 100.0
                            for c in data["conf"]
                            if isinstance(c, (int, float)) and c >= 0
                        ]
                        if word_confs:
                            confidences.append(sum(word_confs) / len(word_confs))
                    except Exception:
                        pass  # confidence is informational

                    pages.append(page_text or "")

                except Exception as page_exc:
                    logger.warning("Chandra: failed on page %d — %s", page_idx + 1, page_exc)
                    pages.append("")

        if not any(p.strip() for p in pages):
            logger.info("Chandra: produced empty output for %s", pdf_path.name)
            return None

        avg_confidence = (
            round(sum(confidences) / len(confidences), 3)
            if confidences else None
        )
        low_dpi_warning = dpi < 200

        extra_meta: dict = {}
        if avg_confidence is not None:
            extra_meta["confidence"] = avg_confidence
        if low_dpi_warning:
            extra_meta["warning"] = f"Low DPI ({dpi}) — accuracy may be reduced"

        logger.info("Chandra: extracted %d pages from %s (langs: %s, avg conf: %s)",
                    len(pages), pdf_path.name, langs, avg_confidence)

        return wrap_markdown(
            pages=pages,
            source_path=pdf_path,
            engine=_ENGINE_NAME,
            extra_meta=extra_meta or None,
        )

    except Exception as exc:
        logger.warning("Chandra engine failed for %s: %s", pdf_path.name, exc)
        return None
