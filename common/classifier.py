"""
classifier.py — Two-tier document validation gate.

Tier 1  (keyword_screen)    — Zero-cost heuristic, runs in < 1 ms.
                              Returns CLINICAL / INSURANCE / UNKNOWN.
                              Used as the first line of defence.

Tier 2  (classify_document_text / classify_document_sync)
                            — LLM-backed definitive classification.
                              Only called when the keyword screen is
                              uncertain (returns UNKNOWN).

Usage
-----
    # In an async FastAPI handler:
    category = await classify_document_text(text)

    # In a sync Celery task:
    category = classify_document_sync(text)

    # Both return one of:  "CLINICAL"  |  "INSURANCE"  |  "INVALID"
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# ── Keyword vocabularies ──────────────────────────────────────────────────────

_CLINICAL_KEYWORDS = [
    # Discharge / admission
    "discharge summary", "date of discharge", "date of admission",
    "hospital course", "chief complaint", "final diagnosis",
    "discharge diagnosis", "condition at discharge",
    # Lab / diagnostics
    "lab no", "collection date", "reference range", "haemoglobin",
    "platelet", "wbc", "rbc", "hba1c", "creatinine", "radiology",
    "x-ray", "mri", "ct scan", "ultrasound", "biopsy", "specimen",
    "impression", "pathology", "laboratory",
    # Clinical general
    "patient name", "age/sex", "diagnosis", "prescription",
    "medication", "allergy", "blood pressure", "pulse rate",
    "temperature", "oxygen saturation", "spo2",
    "doctor", "physician", "consultant", "ward", "opd", "ipd",
]

_INSURANCE_KEYWORDS = [
    "insurance", "insurer", "policy number", "sum insured",
    "premium", "deductible", "co-payment", "co-pay",
    "claim", "pre-authorization", "nhcx", "tpa",
    "waiting period", "exclusion", "benefit", "coverage",
    "insured member", "policyholder", "irdai", "uin",
    "room rent", "icu charges", "reimbursement",
    "network hospital", "cashless", "maternity benefit",
]

# If fewer than this many keyword hits → call the LLM
_KEYWORD_CONFIDENCE_THRESHOLD = 2


def keyword_screen(text: str) -> str:
    """
    Fast, zero-cost heuristic pre-screen.

    Returns
    -------
    "CLINICAL"  — clearly a medical/clinical document
    "INSURANCE" — clearly an insurance/NHCX document
    "UNKNOWN"   — ambiguous; escalate to LLM classifier
    """
    if not text or len(text.strip()) < 50:
        return "UNKNOWN"

    sample = text[:4000].lower()

    clinical_hits  = sum(1 for kw in _CLINICAL_KEYWORDS  if kw in sample)
    insurance_hits = sum(1 for kw in _INSURANCE_KEYWORDS if kw in sample)

    logger.debug("keyword_screen: clinical=%d, insurance=%d", clinical_hits, insurance_hits)

    if clinical_hits >= _KEYWORD_CONFIDENCE_THRESHOLD and clinical_hits > insurance_hits:
        return "CLINICAL"
    if insurance_hits >= _KEYWORD_CONFIDENCE_THRESHOLD and insurance_hits > clinical_hits:
        return "INSURANCE"
    return "UNKNOWN"


# ── LLM prompt ────────────────────────────────────────────────────────────────

_LLM_PROMPT = """
You are an expert medical document classifier.
Analyze the following text extracted from a PDF and classify it into one of these three categories:

1. "CLINICAL": The document is a medical record, such as a discharge summary, lab report, diagnostic report, or clinical note.
2. "INSURANCE": The document is an insurance policy, a claim form, a pre-authorization request, or an insurance-related benefit summary.
3. "INVALID": The document is neither a medical record nor an insurance document (e.g. a random letter, an invoice for non-medical items, or garbage text).

Return ONLY the category name in uppercase: "CLINICAL", "INSURANCE", or "INVALID".

TEXT:
{text}
"""


def _parse_llm_response(raw: str) -> str:
    category = raw.strip().upper()
    if category in ("CLINICAL", "INSURANCE", "INVALID"):
        return category
    if "CLINICAL"  in category: return "CLINICAL"
    if "INSURANCE" in category: return "INSURANCE"
    return "INVALID"


def _llm_classify_sync(text: str) -> str:
    """Blocking LLM call — safe to call from a Celery worker thread."""
    from common.llm_inference_service import LlmInferenceService
    svc = LlmInferenceService()
    try:
        # LlmInferenceService.generate() is async; run it in a new event loop
        loop = asyncio.new_event_loop()
        try:
            raw = loop.run_until_complete(
                svc.generate(
                    prompt=_LLM_PROMPT.format(text=text[:2000]),
                    temperature=0.1,
                    max_output_tokens=10,
                )
            )
        finally:
            loop.close()
        return _parse_llm_response(raw)
    except Exception as exc:
        logger.error("LLM classification failed: %s", exc)
        return "INVALID"


# ── Public API ────────────────────────────────────────────────────────────────

async def classify_document_text(text: str) -> str:
    """
    Async two-tier classifier for FastAPI route handlers.

    1. Runs keyword_screen() (instant, free).
    2. Falls back to LLM only when the heuristic is uncertain.

    Returns "CLINICAL", "INSURANCE", or "INVALID".
    """
    if not text or len(text.strip()) < 50:
        return "INVALID"

    verdict = keyword_screen(text)
    if verdict != "UNKNOWN":
        logger.info("classify_document_text: keyword verdict = %s", verdict)
        return verdict

    # Ambiguous — ask the LLM
    from common.llm_inference_service import LlmInferenceService
    svc = LlmInferenceService()
    try:
        raw = await svc.generate(
            prompt=_LLM_PROMPT.format(text=text[:2000]),
            temperature=0.1,
            max_output_tokens=10,
        )
        verdict = _parse_llm_response(raw)
        logger.info("classify_document_text: LLM verdict = %s", verdict)
        return verdict
    except Exception as exc:
        logger.error("LLM classification failed: %s", exc)
        return "INVALID"


def classify_document_sync(text: str) -> str:
    """
    Synchronous two-tier classifier for Celery task workers.

    1. Runs keyword_screen() (instant, free).
    2. Falls back to LLM only when the heuristic is uncertain.

    Returns "CLINICAL", "INSURANCE", or "INVALID".
    """
    if not text or len(text.strip()) < 50:
        return "INVALID"

    verdict = keyword_screen(text)
    if verdict != "UNKNOWN":
        logger.info("classify_document_sync: keyword verdict = %s", verdict)
        return verdict

    verdict = _llm_classify_sync(text)
    logger.info("classify_document_sync: LLM verdict = %s", verdict)
    return verdict
