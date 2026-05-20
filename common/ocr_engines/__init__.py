"""
common.ocr_engines/__init__.py

Convenience re-exports so callers can do:
    from common.ocr_engines import docling_engine, surya_engine, ...
"""

from common.ocr_engines import (
    chandra_engine,
    docling_engine,
    lighton_engine,
    surya_engine,
)

__all__ = [
    "docling_engine",
    "lighton_engine",
    "surya_engine",
    "chandra_engine",
]
