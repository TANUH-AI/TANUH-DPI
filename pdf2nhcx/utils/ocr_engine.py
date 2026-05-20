# from docling.datamodel.base_models import InputFormat
# from docling.document_converter import DocumentConverter
# import os
# from .logger import get_logger

# logger = get_logger(__name__)

# def classify_document(text: str) -> str:
#     """Classifies the document as either 'discharge_summary' or 'diagnostic_report' based on keywords."""
#     logger.info("Classifying document...")
#     text_lower = text.lower()
#     discharge_keywords = ["discharge", "admission", "course in hospital", "condition at discharge", "hospital course", "chief complaint"]
    
#     discharge_score = sum(1 for kw in discharge_keywords if kw in text_lower)
#     logger.debug(f"Document discharge score: {discharge_score}")
    
#     if discharge_score >= 1:
#         logger.info("Classified as discharge_summary")
#         return "discharge_summary"
#     logger.info("Classified as diagnostic_report")
#     return "diagnostic_report"

# def extract_text_from_pdf(pdf_path):
#     """Extracts text from PDF using Docling and inserts page break markers."""
#     logger.info(f"Extracting text from {pdf_path} using Docling...")
#     converter = DocumentConverter()
#     result = converter.convert(pdf_path)
#     doc = result.document

#     markdown_parts = []
#     current_page = 1
#     for item, _level in doc.iterate_items():
#         page_no = None
#         if hasattr(item, 'prov') and item.prov:
#             page_no = item.prov[0].page_no

#         if page_no and page_no > current_page:
#             # Insert page break marker
#             markdown_parts.append("\n\n<!-- PAGE_BREAK -->\n\n")
#             current_page = page_no

#         # Use the document's method to export individual items if possible.
#         if hasattr(item, 'export_to_markdown'):
#             try:
#                 # Some items might require the doc context
#                 markdown_parts.append(item.export_to_markdown(doc) + "\n")
#             except TypeError:
#                 markdown_parts.append(item.export_to_markdown() + "\n")
#         elif hasattr(item, 'text'):
#             markdown_parts.append(item.text + "\n")

#     logger.info(f"Finished extracting text from {pdf_path}. Total pages detected: {current_page}")
#     return "".join(markdown_parts)


import json

import re
from collections import defaultdict
import base64
import os
from .logger import get_logger

logger = get_logger(__name__)



# ── NHCX bundle type definitions imported from single source of truth ─────────
from pdf2nhcx.utils.nhcx_profiles import (
    NHCX_BUNDLE_TYPES as _NHCX_BUNDLE_TYPES,
    get_must_resources,
    get_allowed_supporting,
    BUNDLE_MUST_RESOURCES as _BUNDLE_MUST_RESOURCES,
)

import re
def select_nhcx_resources(distilled_text):
    nhcx_extraction_dictionary = {
        "NHCXArtifact": {
            "InsurancePlanBundle":               "A Bundle describing a health insurance product: covered benefits, plan costs, ownership and administration. Select when the document is an insurance policy brochure or product listing.",
            "ClaimBundle":                       "A Bundle for submitting a healthcare claim to an insurer for reimbursement, preauthorization, or predetermination. Select when the document is a claim submission form or bill.",
            "ClaimResponseBundle":               "A Bundle containing the payer's adjudication result for a submitted Claim — including payment, partial payment, or denial. Select when the document is a claim decision or Explanation of Benefits (EOB).",
            "CoverageEligibilityRequestBundle":  "A Bundle used to check whether a patient has active coverage for specific services. Select when the document is an eligibility verification request.",
            "CoverageEligibilityResponseBundle": "A Bundle with the payer's eligibility response: covered services, limits, co-pays, authorizations. Select when the document is an eligibility response.",
            "TaskBundle":                        "A Bundle for workflow tasks: payment status, supporting document requests, or status queries during claim adjudication. Select when the document relates to task-based communications.",
        },
        "OtherResources": {
            "InsurancePlan": "Represents the health insurance product/plan provided by an organization.",
            "Claim": "A provider-issued list of services/products sent to an insurer for reimbursement or preauthorization.",
            "ClaimResponse": "The payer's adjudication result in response to a Claim.",
            "Coverage": "Insurance plan details for a patient linking the beneficiary to a specific policy.",
            "CoverageEligibilityRequest": "Request to check patient coverage for specific services.",
            "CoverageEligibilityResponse": "Payer's eligibility response with plan details and authorizations.",
            "Task": "Workflow task for status checks, document requests, or payment notifications.",
            "Communication": "Record of an exchange of information between provider and payer.",
            "CommunicationRequest": "Record of a request for communication (e.g., request for additional documents).",
            "PaymentNotice": "Notification that a payment has been made or payment status has changed.",
            "PaymentReconciliation": "Detailed breakdown reconciling a bulk payment against multiple claims.",
            "Organization": "Healthcare organization, insurer, or TPA information.",
            "Patient": "Basic demographics and administrative information about an individual beneficiary.",
            "Practitioner": "Demographics and administrative info about a healthcare professional.",
            "PractitionerRole": "Roles, specialties, and locations of a practitioner within an organization.",
            "Condition": "List of conditions, problems, or diagnoses associated with a patient.",
            "Procedure": "Clinical procedures performed on a patient, mapped to claim line items.",
            "DocumentReference": "Reference to a supporting document (clinical note, lab report, etc.).",
            "Binary": "Raw digital content (scanned PDF, image) in its native format.",
        }
    }

    prompt = f"""
    ACT AS an expert NHCX FHIR Data Architect.

    **TASK:**
    1. Select the SINGLE most appropriate NHCX artifact type from the `NHCXArtifact` section based on the document content.
    2. Select any additional FHIR resources from `OtherResources` that have matching data in the document.

    **RULES:**
    1. **Artifact Selection**: Choose from NHCXArtifact based on the document's primary purpose (policy brochure → InsurancePlanBundle, claim form → ClaimBundle, adjudication letter → ClaimResponseBundle, eligibility check → CoverageEligibilityRequestBundle or CoverageEligibilityResponseBundle, task/workflow → TaskBundle).
    2. **Source Strictly from Text**: Only select an OtherResource if the document contains specific data points for that profile.
    3. **Exclude Mandatory Base**: Do NOT list resources already mandatory for the selected artifact (e.g. if ClaimBundle is chosen, do not add Claim or Patient in other resources).
    4. **Accuracy**: If the text mentions a Diagnosis → Condition. Surgery → Procedure. Co-pay/deductible → Coverage.

    **INPUT:**
    [Extracted Text]:
    {distilled_text}

    [Dictionary]:
    {json.dumps(nhcx_extraction_dictionary, indent=2)}

    **OUTPUT FORMAT:**
    Return ONLY a valid JSON object. No preamble, markdown blocks, or explanation.
    {{
        "selected_artifact": "ClaimBundle",
        "selected_other_resources": ["Key1", "Key2"]
    }}
    """

    from .llm_requirements import get_llm
    fresh_llm = get_llm()
    response = fresh_llm.invoke(prompt)
    raw_output = response.content.strip()

    _KNOWN_ARTIFACTS = set(_BUNDLE_MUST_RESOURCES.keys())

    # Parsing Logic
    try:
        clean_json = re.sub(r'^```json\s*|```$', '', raw_output, flags=re.MULTILINE).strip()
        data = json.loads(clean_json)

        # LLM-selected artifact (with safe fallback)
        clinical_artifact = data.get("selected_artifact", "InsurancePlanBundle")
        if clinical_artifact not in _KNOWN_ARTIFACTS:
            print(f"⚠️ Unknown artifact '{clinical_artifact}', falling back to InsurancePlanBundle")
            clinical_artifact = "InsurancePlanBundle"

        must_resources = get_must_resources(clinical_artifact)
        selected_other_resources = [
            res for res in data.get("selected_other_resources", [])
            if res not in must_resources
        ]

        print(f"--- Extraction Complete ---")
        print(f"Artifact: {clinical_artifact}")
        print(f"Must Resources: {must_resources}")
        print(f"Other Selected Resources: {selected_other_resources}")

    except Exception as e:
        print(f"Error parsing LLM output: {e}")
        print(f"Raw response was: {raw_output}")
        clinical_artifact = "InsurancePlanBundle"
        must_resources = get_must_resources(clinical_artifact)
        selected_other_resources = []

    return clinical_artifact, must_resources, selected_other_resources

import math
from langchain_core.messages import HumanMessage

import math
from langchain_core.messages import HumanMessage

def distill_insurance_text(full_text):
    """
    Distil insurance policy text into a high-density fact sheet for FHIR extraction.

    Optimisations vs original:
    - Chunks reduced 8 -> 4  (Gemma 4 handles larger context comfortably)
    - Chunks processed in parallel with ThreadPoolExecutor (max 4 workers)
    - Serial 8-call latency (~8-12 min) -> parallel 4-call latency (~60-90 s)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    num_chunks = 4
    overlap_size = 2000
    total_len = len(full_text)
    chunk_size = math.ceil(total_len / num_chunks)

    chunks = []
    for i in range(num_chunks):
        start = max(0, i * chunk_size - overlap_size)
        end = min(total_len, (i + 1) * chunk_size)
        chunks.append(full_text[start:end])

    distill_prompt_template = (
        "ACT AS an Insurance Policy Underwriter. Simplify this policy text into a high-density Fact Sheet.\n\n"
        "STRICT EXTRACTION RULES:\n"
        "1. CAPTURE ALL NUMERICS: Every INR value, percentage, day limit, or age limit must be preserved.\n"
        "2. PRESERVE TABLES: Recreate benefit/limit tables as Markdown tables.\n"
        "3. NO NARRATIVE: State facts only.\n"
        "4. KEEP TERMINOLOGY: Preserve medical/insurance terms exactly.\n"
        "5. INSURANCE PLAN DETAILS: Extract all plan details, covered benefits, costs, limits, waiting periods.\n\n"
        "TEXT CONTENT:\n{chunk_text}\n\n"
        "OUTPUT: Condensed facts only. If no insurance data present, return: [NO_INSURANCE_DATA]"
    )

    print(f"Distilling {total_len} chars across {num_chunks} chunks (parallel)...")

    def _process_chunk(args):
        i, chunk = args
        try:
            from .llm_requirements import get_llm
            llm = get_llm()
            response = llm.invoke([HumanMessage(content=distill_prompt_template.format(chunk_text=chunk))])
            content = response.content.strip()
            if "[NO_INSURANCE_DATA]" not in content:
                return i, f"### SECTION {i+1} SUMMARY ###\n{content}"
        except Exception as e:
            print(f"distill section {i+1} error: {e}")
        return i, None

    results: dict = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_process_chunk, (i, chunk)): i for i, chunk in enumerate(chunks)}
        for future in as_completed(futures):
            i, content = future.result()
            if content:
                results[i] = content

    distilled_outputs = [results[i] for i in sorted(results.keys())]
    final_distilled_text = "\n\n".join(distilled_outputs)
    print(f"Distillation done. Original: {total_len} chars -> Distilled: {len(final_distilled_text)} chars")
    return final_distilled_text


async def extract_raw_text_from_nhcx_pdf(pdf_path):
    """
    OCR only — returns (raw_markdown, pdf_base64) WITHOUT distillation.
    Use this for a fast pre-classification check before committing to the
    expensive 8-chunk LLM distillation step.
    """
    from common.ocr_service import extract_pdf_to_markdown, OcrEngine
    from pathlib import Path

    logger.info(f"[NHCX OCR] Extracting raw text from {pdf_path}...")
    result = await extract_pdf_to_markdown(Path(pdf_path), engine=OcrEngine.AUTO)
    extracted_text = result.markdown

    with open(pdf_path, "rb") as pdf_file:
        pdf_base64 = base64.b64encode(pdf_file.read()).decode("utf-8")

    return extracted_text, pdf_base64


async def extract_distilled_text_from_nhcx_pdf(pdf_path):
    """Extract and distil text from an insurance PDF for NHCX processing."""
    raw_text, pdf_base64 = await extract_raw_text_from_nhcx_pdf(pdf_path)
    distilled_text = distill_insurance_text(raw_text)
    return distilled_text, pdf_base64