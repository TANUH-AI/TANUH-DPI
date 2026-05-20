"""
surya_engine.py — Surya OCR adapter

Best for: scanned PDFs and image-heavy documents. Surya uses a
          transformer-based detector + recogniser trained on 90+ languages.
          Significantly better than Tesseract for Indian language scripts
          (Devanagari, Tamil, Telugu, etc.) and low-quality scans.

Surya pipeline:
  1. PDF page → PIL Image (via PyMuPDF)
  2. Line detection (SuryaDetector)
  3. Text recognition (SuryaRecognizer)
  4. Lines → Markdown text block per page

Install: pip install "surya-ocr>=0.7" "pymupdf>=1.24" "Pillow>=10.0"

GPU note: Surya uses PyTorch. On CPU it is slower (~5-20s/page).
          Set SURYA_DEVICE=cpu explicitly if no GPU is available.
"""

from __future__ import annotations

import logging
from pathlib import Path

from common.ocr_engines.normaliser import wrap_markdown

logger = logging.getLogger(__name__)

_ENGINE_NAME = "surya"


def run(
    pdf_path: Path,
    language_hints: list[str] | None = None,
    page_limit: int | None = None,
) -> str | None:
    """
    Convert a PDF to Markdown using Surya OCR.

    Args:
        pdf_path:       Path to the PDF file.
        language_hints: ISO 639-1 codes (e.g. ["en", "hi"]) passed to the recogniser.
        page_limit:     If set, process only the first N pages.

    Returns:
        Markdown string on success, None if unavailable or output is empty.
    """
    try:
        from surya.recognition import RecognitionPredictor   # type: ignore[import]
        from surya.detection import DetectionPredictor       # type: ignore[import]
        import fitz                                          # type: ignore[import]
        from PIL import Image                                # type: ignore[import]
    except (ImportError, Exception) as _import_err:
        logger.warning("surya-ocr unavailable — skipping Surya engine (%s). "
                       "Install with: pip install 'surya-ocr>=0.7'", _import_err)
        return None

    try:
        langs = language_hints or ["en"]
        # Surya expects full language names for some models; keep as-is for OCR codes
        recognition_predictor = RecognitionPredictor()
        detection_predictor = DetectionPredictor()

        pages: list[str] = []
        total_confidences: list[float] = []

        with fitz.open(str(pdf_path)) as doc:
            total_pages = doc.page_count
            page_indices = list(range(total_pages))
            if page_limit:
                page_indices = page_indices[:page_limit]

            for page_idx in page_indices:
                try:
                    page = doc[page_idx]
                    # Render at 2x resolution for better OCR accuracy
                    mat = fitz.Matrix(2.0, 2.0)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                    # Run detection + recognition
                    predictions = recognition_predictor(
                        [img],
                        [langs],
                        detection_predictor,
                    )
                    page_result = predictions[0]

                    # Extract text lines in reading order
                    lines: list[str] = []
                    confidences: list[float] = []
                    for text_line in page_result.text_lines:
                        if text_line.text.strip():
                            lines.append(text_line.text.strip())
                            if hasattr(text_line, "confidence"):
                                confidences.append(text_line.confidence)

                    page_text = "\n".join(lines)
                    pages.append(page_text)
                    total_confidences.extend(confidences)

                except Exception as page_exc:
                    logger.warning("Surya: failed on page %d — %s", page_idx + 1, page_exc)
                    pages.append("")

        if not any(p.strip() for p in pages):
            logger.info("Surya: produced empty output for %s", pdf_path.name)
            return None

        avg_confidence = (
            round(sum(total_confidences) / len(total_confidences), 3)
            if total_confidences else None
        )

        logger.info("Surya: extracted %d pages from %s (avg confidence: %s)",
                    len(pages), pdf_path.name, avg_confidence)

        return wrap_markdown(
            pages=pages,
            source_path=pdf_path,
            engine=_ENGINE_NAME,
            extra_meta={"confidence": avg_confidence} if avg_confidence else None,
        )

    except Exception as exc:
        logger.warning("Surya engine failed for %s: %s", pdf_path.name, exc)
        return None
