"""
normaliser.py -- Shared Markdown normalisation and front-matter generation.

Every OCR engine adapter calls wrap_markdown() to produce a uniform
AI-ingestible output regardless of which engine ran.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


def wrap_markdown(
    pages: list[str],
    source_path: Path | str,
    engine: str,
    extra_meta: dict | None = None,
) -> str:
    """
    Combine per-page markdown strings into a single AI-ingestible document.
    """
    now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    source_name = Path(source_path).name

    meta_lines = [
        "---",
        f"source: {source_name}",
        f"engine: {engine}",
        f"pages: {len(pages)}",
        f"extracted_at: {now}",
    ]
    if extra_meta:
        for k, v in extra_meta.items():
            meta_lines.append(f"{k}: {v}")
    meta_lines.append("---")
    front_matter = "\n".join(meta_lines)

    page_sections: list[str] = []
    for i, page_text in enumerate(pages, start=1):
        cleaned = _clean_page(page_text)
        if cleaned:
            page_sections.append(f"<!-- PAGE {i} -->\n\n{cleaned}")

    body = "\n\n---\n\n".join(page_sections)
    return f"{front_matter}\n\n{body}\n"


def _clean_page(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
