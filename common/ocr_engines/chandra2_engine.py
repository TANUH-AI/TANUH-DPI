"""
chandra2_engine.py — Chandra 2 OCR adapter

Best for: High-accuracy extraction of complex documents (tables, math, handwriting)
          using Datalab's Chandra 2 Vision-Language Model.

Prerequisites:
  pip install transformers accelerate torch Pillow pymupdf

Note: This is a 4-Billion parameter model. Inference on a CPU will be very slow.
      A GPU with at least 8GB-12GB VRAM is highly recommended.
"""

from __future__ import annotations

import logging
from pathlib import Path

from common.ocr_engines.normaliser import wrap_markdown

logger = logging.getLogger(__name__)

_ENGINE_NAME = "chandra2"
_MODEL_ID = "datalab/chandra2" # Placeholder for the exact HF Model ID


def run(
    pdf_path: Path,
    language_hints: list[str] | None = None,
    page_limit: int | None = None,
) -> str | None:
    """
    Convert a PDF to Markdown using the Chandra 2 VLM OCR.
    """
    try:
        import torch
        from transformers import AutoProcessor, AutoModelForCausalLM
        from PIL import Image
        import fitz  # PyMuPDF
    except (ImportError, Exception) as _import_err:
        logger.warning(
            "transformers/torch/Pillow/pymupdf unavailable — skipping Chandra 2 engine (%s). "
            "Install with: pip install transformers accelerate torch Pillow pymupdf",
            _import_err
        )
        return None

    try:
        # 1. Load Model and Processor (Cached locally in ~/.cache/huggingface)
        device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        logger.info(f"Loading Chandra 2 model on {device}... This may take a while the first time.")
        
        # Load in half-precision if on GPU to save memory
        torch_dtype = torch.float16 if device != "cpu" else torch.float32
        
        processor = AutoProcessor.from_pretrained(_MODEL_ID, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            _MODEL_ID, 
            torch_dtype=torch_dtype,
            trust_remote_code=True,
            device_map="auto" if device == "cuda" else None
        )
        if device != "cuda":
            model.to(device)

        pages: list[str] = []

        # 2. Extract PDF pages as Images
        with fitz.open(str(pdf_path)) as doc:
            total_pages = doc.page_count
            page_indices = list(range(total_pages))
            if page_limit:
                page_indices = page_indices[:page_limit]

            for page_idx in page_indices:
                try:
                    logger.info(f"Chandra 2: Processing page {page_idx + 1}/{len(page_indices)}...")
                    page = doc[page_idx]
                    # High resolution needed for VLM OCR
                    mat = fitz.Matrix(3.0, 3.0) 
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

                    # 3. Prepare Prompt
                    # Standard prompt for Chandra 2 / olmOCR to extract full markdown
                    prompt = "Convert this document image into properly formatted Markdown, preserving tables, equations, and structure."
                    
                    inputs = processor(
                        text=prompt, 
                        images=img, 
                        return_tensors="pt"
                    ).to(device, dtype=torch_dtype if device != "cpu" else None)

                    # 4. Generate Markdown
                    with torch.no_grad():
                        generated_ids = model.generate(
                            **inputs,
                            max_new_tokens=4096,
                            temperature=0.2,
                            do_sample=False
                        )
                    
                    generated_text = processor.batch_decode(
                        generated_ids, skip_special_tokens=True
                    )[0]
                    
                    # Clean out the prompt from the response if the model echoes it
                    if generated_text.startswith(prompt):
                        generated_text = generated_text[len(prompt):].strip()

                    pages.append(generated_text)

                except Exception as page_exc:
                    logger.warning("Chandra 2: failed on page %d — %s", page_idx + 1, page_exc)
                    pages.append("")

        if not any(p.strip() for p in pages):
            logger.info("Chandra 2: produced empty output for %s", pdf_path.name)
            return None

        logger.info("Chandra 2: extracted %d pages from %s", len(pages), pdf_path.name)

        return wrap_markdown(
            pages=pages,
            source_path=pdf_path,
            engine=_ENGINE_NAME,
        )

    except Exception as exc:
        logger.warning("Chandra 2 engine failed for %s: %s", pdf_path.name, exc)
        return None
