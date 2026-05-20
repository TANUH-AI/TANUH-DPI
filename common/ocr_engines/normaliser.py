"""
normaliser.py — Shared Markdown normalisation and front-matter generation.

Every OCR engine adapter calls `wrap_markdown()` to produce a uniform
AI-ingestible output regardless of which engine ran.

Output schema
-------------
---
source: claim.pdf
engine: docling
pages: 3
extracted_at: 2026-04-22T07:29:09+05:30
---

<!-- PAGE 1 -->

## Heading ...

| Col A | Col B |
|-------|-------|
| v     | v     |

---

<!-- PAGE 2 -->

Plain paragraph text...
"""

from __future__ import annotations

import re
import textwrap
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

    Args:
        pages:       List of markdown strings, one per PDF page (1-indexed order).
        source_path: Original PDF path — used only for the front-matter `source` field.
        engine:      Name of the OCR engine that produced the output.
        extra_meta:  Optional additional YAML front-matter fields (e.g. confidence).

    Returns:
        Full markdown string with YAML front-matter and <!-- PAGE N --> markers.
    """
    now = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    source_name = Path(source_path).name

    # ── YAML front-matter ─────────────────────────────────────────────────────
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

    # ── Page sections ─────────────────────────────────────────────────────────
    page_sections: list[str] = []
    for i, page_text in enumerate(pages, start=1):
        cleaned = _clean_page(page_text)
        if cleaned:
            page_sections.append(f"<!-- PAGE {i} -->\n\n{cleaned}")

    body = "\n\n---\n\n".join(page_sections)
    return f"{front_matter}\n\n{body}\n"


def combine_raw_text(text: str, source_path: Path | str, engine: str) -> str:
    """
    Wrap a single flat text string (no per-page split) as a one-page document.
    Used when an engine returns a single blob instead of page-by-page output.
    """
    return wrap_markdown(
        pages=[text],
        source_path=source_path,
        engine=engine,
    )


def _clean_page(text: str) -> str:
    """
    Light normalisation applied to every page regardless of engine:
    - Strip leading/trailing whitespace per page
    - Collapse 3+ consecutive blank lines to 2
    - Normalise Windows line endings
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
