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

def extract_metadata(page_text):
    """
    Extract key metadata used for grouping.
    We use Age/Sex + Collection Date (DATE ONLY) as primary fingerprint.
    """

    # Extract Age/Sex
    age_sex_match = re.search(r'Age/Sex\s*:\s*(.*)', page_text)
    age_sex = age_sex_match.group(1).strip() if age_sex_match else "UNKNOWN"

    # Extract ONLY date part (ignore time)
    collection_match = re.search(
        r'Collection Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4})',
        page_text
    )
    collection_date = collection_match.group(1) if collection_match else "UNKNOWN"

    # Extract Lab No (optional for debugging)
    lab_no_match = re.search(r'Lab No\.\s*:\s*(.*)', page_text)
    lab_no = lab_no_match.group(1).strip() if lab_no_match else "UNKNOWN"

    print(f"Extracted Metadata - Age/Sex: {age_sex}, Collection Date: {collection_date}, Lab No: {lab_no}")

    return age_sex, collection_date

def is_lab_report_pdf(pages_text: list) -> bool:
    """
    Return True only when at least one page carries real lab-specific metadata
    (Age/Sex AND Collection Date fields), meaning this PDF is a multi-patient
    lab/diagnostic batch.  Discharge Summaries and other clinical documents
    will NOT have these fields and must NOT be split by patient.
    """
    for page_text in pages_text:
        has_age_sex = bool(re.search(r'Age/Sex\s*:', page_text))
        has_collection_date = bool(re.search(
            r'Collection Date\s*:\s*[0-9]{2}-[A-Za-z]{3}-[0-9]{4}', page_text
        ))
        if has_age_sex and has_collection_date:
            return True
    return False


def group_pages_by_patient(pages_text):
    """
    Group pages belonging to the same patient using a strong fingerprint.

    IMPORTANT: This grouping is ONLY meaningful for multi-patient lab/diagnostic
    batch PDFs.  Call `is_lab_report_pdf()` first; if it returns False, skip
    this function and treat all pages as a single patient document.
    """

    grouped = defaultdict(list)

    for page_number, page_text in enumerate(pages_text, start=1):
        age_sex, collection_date = extract_metadata(page_text)

        fingerprint = f"{age_sex}_{collection_date}"

        grouped[fingerprint].append((page_number, page_text))

    final_patient_texts = []

    print("\n📌 GROUPING SUMMARY")
    print("=" * 50)

    for patient_index, (key, page_data) in enumerate(grouped.items(), start=1):

        page_numbers = [str(page_num) for page_num, _ in page_data]
        merged_text = "\n\n".join([text for _, text in page_data])

        final_patient_texts.append(merged_text)

        age_sex, collection_date = key.split("_", 1)

        if len(page_numbers) > 1:
            print(f"🟢 Patient {patient_index} ({age_sex}, {collection_date})")
            print(f"   → Merged Pages: {', '.join(page_numbers)}")
        else:
            print(f"🔵 Patient {patient_index} ({age_sex}, {collection_date})")
            print(f"   → Single Page: {page_numbers[0]}")

        print("-" * 50)

    return final_patient_texts


async def process_pdf_and_group_patients(pdf_path):
    """
    MAIN FUNCTION using Multi-Engine OCR.

    For lab/diagnostic batch PDFs (multi-patient): groups pages by patient
    fingerprint (Age/Sex + Collection Date) → one bundle per patient.

    For Discharge Summaries and other single-patient clinical documents:
    skips the grouping step entirely and returns a single merged bundle,
    avoiding the bug where each page was treated as a separate patient.
    """
    from common.ocr_service import extract_pdf_to_markdown, split_markdown_into_pages, OcrEngine
    from pathlib import Path

    # Step 1: Convert using Multi-Engine OCR
    logger.info(f"Extracting text from {pdf_path} using Multi-Engine OCR...")
    result = await extract_pdf_to_markdown(Path(pdf_path), engine=OcrEngine.AUTO)

    with open(pdf_path, "rb") as pdf_file:
        pdf_bytes = pdf_file.read()
        pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")

    # Step 2: Extract page-wise text
    pages_text = split_markdown_into_pages(result.markdown)

    print(f"\n✅ Extracted {len(pages_text)} pages successfully using {result.engine_used}!")

    # Step 3: Decide whether to group by patient or treat as a single document.
    #
    # The page-grouping logic uses 'Age/Sex' + 'Collection Date' fingerprints
    # that only exist in lab/diagnostic batch reports.  Discharge Summaries
    # do NOT carry these fields, so every page would produce the same
    # 'UNKNOWN_UNKNOWN' key — or worse, slightly different whitespace variants
    # that split the document into spurious per-page bundles.
    #
    # Fix: if the PDF is NOT a lab batch, merge all pages into one text blob
    # and return it as a single-patient document → exactly 1 FHIR bundle.
    if is_lab_report_pdf(pages_text):
        print("📋 Detected lab/diagnostic batch PDF — grouping pages by patient fingerprint.")
        unique_patient_texts = group_pages_by_patient(pages_text)
    else:
        print("📄 Detected single-patient clinical document (e.g. Discharge Summary) — "
              "merging all pages into one bundle (no per-patient split).")
        merged_text = "\n\n".join(pages_text)
        unique_patient_texts = [merged_text]

    print(f"\n🎯 Total Unique Patients Identified: {len(unique_patient_texts)}")

    return unique_patient_texts, pdf_base64




import os
from .logger import get_logger

def get_must_resources(artifact):
    if artifact == "DiagnosticReportRecord":
        return [
            "DocumentBundle", "DiagnosticReportRecord", "Patient", "Practitioner", 
            "Organization", "DiagnosticReportLab", "Observation", "DocumentReference"
        ]
    elif artifact == "DischargeSummaryRecord":
        return [
            "DocumentBundle", "DischargeSummaryRecord", "Patient", "Encounter", "Practitioner", 
            "Organization", "Condition", "Procedure", "Specimen", "Appointment", 
            "Observation", "DocumentReference"
        ]
    return []

logger = get_logger(__name__)

def classify_document(text: str) -> list:
    print("\n🔍 Classifying document type and required resources using LLM...")
    abdm_extraction_dictionary = {
        "ClinicalArtifacts": {
            "DischargeSummaryRecord": "A Clinical document used to represent the discharge summary record for ABDM HDE data set. It provides a single coherent clinical statement with clinical attestation of a patient's stay.",
            "DiagnosticReportRecord": "A Clinical Artifact representing diagnostic reports, including Radiology and Laboratory reports, that can be shared across the health ecosystem. It provides a single coherent statement of meaning with clinical attestation.",
        },
        "OtherResources": {
            "Patient": "This profile sets minimum expectations for the Patient resource to record, search, and fetch basic demographics and other administrative information about an individual patient.",
            "Practitioner": "This profile sets minimum expectations for the Practitioner resource to record, search, and fetch basic demographics and other administrative information about an individual practitioner.",
            "PractitionerRole": "This profile sets minimum expectations for the PractitionerRole resource to record, search, and fetch the practitioner role for a practitioner within an organization.",
            "Organization": "This profile sets minimum expectations for the Organization resource to record, search, and fetch information about a healthcare organization.",
            "Encounter": "This profile sets minimum expectations for the Encounter resource to record, search, and fetch basic encounter information for an individual patient, such as inpatient or outpatient status.",
            "Condition": "This profile sets minimum expectations for the Condition resource to record, search, and fetch a list of conditions, problems, or diagnoses associated with a patient.",
            "Procedure": "This profile sets minimum expectations for the Procedure resource to record, search, and fetch details of clinical actions or procedures performed on or with a patient.",
            "Observation": "Represents an individual laboratory test and result value, or a finding. It sets minimum expectations for the Observation resource to record, search, and fetch clinical observations associated with a patient.",
            "DiagnosticReportLab": "This profile represents the set of information related to the Laboratory diagnosis report generated by laboratory services like CBC, Lipid Panel, Urinalysis, etc.",
            "DiagnosticReportImaging": "This profile represents the set of information related to the Imaging diagnosis report generated by imaging services like Radiology, Cardiology, or Endoscopy.",
            "ObservationVitalSigns": "This profile sets minimum expectations for the Observation resource to record, search, and fetch vital signs like Blood Pressure, Heart Rate, and Temperature.",
            "ObservationBodyMeasurement": "This profile sets minimum expectations for the Observation resource to record, search, and fetch physical metrics such as Body Weight, Height, and BMI.",
            "ObservationGeneralAssessment": "This profile sets minimum expectations for the ObservationGeneralAssessment to record, search, and fetch the details of the general health assessment or qualitative scores of a patient.",
            "ObservationLifestyle": "This profile sets minimum expectations for the ObservationLifestyle to record, search, and fetch details of the lifestyle of the patient (e.g., smoking or alcohol status).",
            "ObservationPhysicalActivity": "This profile sets minimum expectations for the ObservationPhysicalActivity to record, search, and fetch details of the physical movement and exercise levels of the patient.",
            "ObservationWomenHealth": "This profile sets minimum expectations for the Observation resource to record specific metrics related to obstetric and gynecological history, such as LMP and pregnancy status.",
            "MedicationRequest": "This resource is used to record a patient's medication prescription or order. It sets minimum expectations to record, search, and fetch medications associated with a patient.",
            "MedicationStatement": "Used to record a patient's medication information, specifically medications consumed by the patient in the past, present, or future.",
            "Medication": "This profile sets the minimum expectations for the medication resource in order to store various details about a given medicine (ingredients, form, etc.).",
            "AllergyIntolerance": "Records the risk of harmful or undesirable physiological response unique to an individual associated with exposure to a substance (food, drug, or material).",
            "FamilyMemberHistory": "This profile sets minimum expectations to record, search, and fetch significant health conditions of the patient's relatives for risk assessment.",
            "Immunization": "This profile sets minimum expectations for the Immunization resource to record, fetch, and search immunization history and vaccine administration associated with a patient.",
            "CarePlan": "This profile sets minimum expectations for the CarePlan resource to record, search, and fetch assessment and plan of treatment data associated with a patient.",
            "ServiceRequest": "A record of a request for service such as diagnostic investigations, treatments, or referrals to be performed.",
            "Specimen": "This profile sets minimum expectations for the Specimen resource to record details about a biological sample (blood, urine, etc.) used in diagnostic testing.",
            "ImagingStudy": "Representation of the content produced in a DICOM imaging study, comprising a set of series and instances (images) acquired in a common context.",
            "DocumentReference": "This profile sets minimum expectations for searching and fetching patient documents, including clinical notes, using a reference to a document.",
            "Binary": "This profile sets minimum expectations for the Binary resource to search and fetch the data of a single raw artifact (e.g., PDF or scanned image) in its native format.",
            "Media": "This profile sets minimum expectations for the Media resource to search and fetch media like a photo, video, or audio recording acquired or used in healthcare."
        }
    }
    
    # The Optimized Prompt
    prompt = f"""
    ACT AS an expert ABDM FHIR Data Architect.

    TASK:
    1. Analyze the [Extracted Text] and select the most appropriate key from [ClinicalArtifacts].
    2. Select any relevant keys from [RemainingResources] that are explicitly mentioned in the text. 
    - DO NOT select resources that are already part of the Mandatory Base for your chosen artifact.
    - The number of selected resources can be zero or more depending on the text content.

    INPUT:
    [Extracted Text]: 
    {text}

    [Dictionary]:
    {json.dumps(abdm_extraction_dictionary, indent=2)}

    OUTPUT FORMAT:
    Return ONLY a valid JSON object. No pre-amble or markdown blocks.
    {{
        "clinical_artifact": "SelectedKeyFromClinicalArtifacts",
        "selected_other_resources": ["Key1", "Key2", ...]
    }}
    """

    # Safe defaults — guaranteed to be defined even if LLM/parsing fails
    clinical_artifact = ""
    must_resources = []
    selected_other_resources = []

    # Invoke the LLM with a fresh client (token baked in at construction)
    from .llm_requirements import get_llm
    fresh_llm = get_llm()
    response = fresh_llm.invoke(prompt)
    raw_output = response.content.strip()

    # Parsing Logic
    try:
        # Clean up potential markdown formatting
        clean_json = re.sub(r'^```json\s*|```$', '', raw_output, flags=re.MULTILINE).strip()
        data = json.loads(clean_json)
        
        # Final Variables
        clinical_artifact = data.get("clinical_artifact", "")
        must_resources = get_must_resources(clinical_artifact)
        selected_other_resources = data.get("selected_other_resources", [])
        selected_other_resources = [res for res in selected_other_resources 
                            if res not in must_resources]
        
        # Logging the results
        print(f"--- Extraction Complete ---")
        print(f"Artifact: {clinical_artifact}")
        print(f"Must Resources (Fixed): {must_resources}")
        print(f"Other Selected Resources: {selected_other_resources}")

    except Exception as e:
        print(f"⚠ Error parsing LLM output: {e}")
        print(f"Raw response was: {raw_output}")
        print("⚙ Falling back to keyword-based classification...")

        # Keyword fallback — never let a document return empty-handed
        text_lower = text.lower()
        discharge_keywords = [
            "discharge", "admission", "course in hospital",
            "condition at discharge", "hospital course", "chief complaint",
            "final diagnosis", "discharge diagnosis", "date of admission",
            "date of discharge", "inpatient"
        ]
        diagnostic_keywords = [
            "lab no", "collection date", "report date", "test name",
            "reference range", "haemoglobin", "platelet", "radiology",
            "impression", "x-ray", "mri", "ct scan", "ultrasound",
            "laboratory", "pathology", "biopsy", "specimen"
        ]
        discharge_score  = sum(1 for kw in discharge_keywords  if kw in text_lower)
        diagnostic_score = sum(1 for kw in diagnostic_keywords if kw in text_lower)

        if discharge_score >= diagnostic_score:
            clinical_artifact = "DischargeSummaryRecord"
            print(f"  → Fallback classified as DischargeSummaryRecord (score {discharge_score} vs {diagnostic_score})")
        else:
            clinical_artifact = "DiagnosticReportRecord"
            print(f"  → Fallback classified as DiagnosticReportRecord (score {diagnostic_score} vs {discharge_score})")

        must_resources = get_must_resources(clinical_artifact)
        selected_other_resources = []

    return clinical_artifact, must_resources, selected_other_resources


async def extract_text_from_abdm_pdf(pdf_path):
    """Extracts text from PDF using multi-engine OCR and groups patients."""
    logger.info(f"Extracting text from {pdf_path}...")

    unique_patient_lists, pdf_base64 = await process_pdf_and_group_patients(pdf_path)

    return unique_patient_lists, pdf_base64


# ═══════════════════════════════════════════════════════════════════════════════
# NHCX (Insurance) functions — also needed by pdf2nhcx/tasks.py.
# The Dockerfile copies this file last onto /app/utils/ocr_engine.py, so both
# services share it.  Keep NHCX functions in sync with pdf2nhcx/utils/ocr_engine.py.
# ═══════════════════════════════════════════════════════════════════════════════

import math
from langchain_core.messages import HumanMessage


def _nhcx_get_must_resources(artifact):
    if artifact == "InsurancePlanBundle":
        return [
            "InsurancePlanBundle", "InsurancePlan", "Organization", "Condition", "DocumentReference"
        ]
    return []


def select_nhcx_resources(distilled_text):
    """Select relevant NHCX FHIR resources based on distilled insurance text."""
    import json as _json
    nhcx_dict = {
        "NHCXArtifact": {
            "InsurancePlanBundle": "Bundle of type collection describing a health insurance package."
        },
        "OtherResources": {
            "InsurancePlan": "Health insurance product/plan provided by an organization.",
            "Claim": "Provider-issued list of services sent to an insurer for reimbursement.",
            "ClaimResponse": "Adjudication results from a payer in response to a Claim.",
            "Coverage": "Insurance plan details for a patient linking them to a specific policy.",
            "CoverageEligibilityRequest": "Request to check patient insurance coverage for specific services.",
            "CoverageEligibilityResponse": "Response providing eligibility and plan details.",
            "Task": "Conveys payment information and status checks during claim adjudication.",
            "Communication": "Record of exchange of information between sender and receiver.",
            "CommunicationRequest": "Request for a communication to take place.",
            "PaymentNotice": "Notification that a payment has been made.",
            "PaymentReconciliation": "Reconciles a bulk payment against multiple claims.",
            "Organization": "Healthcare organizations, insurers, or TPAs.",
            "Patient": "Individual beneficiary demographics.",
            "Practitioner": "Healthcare professional demographics.",
            "PractitionerRole": "Roles and specialties of a practitioner within an organization.",
            "Condition": "Conditions/diagnoses associated with a patient in claims.",
            "Procedure": "Clinical actions performed on a patient mapped to claim line items.",
            "DocumentReference": "Reference to a document supporting the claim.",
            "Binary": "Raw digital content (scanned PDF, brochure) in native format.",
        }
    }

    prompt = f"""
    ACT AS an expert NHCX FHIR Data Architect.
    Select relevant FHIR resources from OtherResources based ONLY on the text below.
    [Extracted Text]: {distilled_text}
    [Dictionary]: {_json.dumps(nhcx_dict, indent=2)}
    Return ONLY valid JSON: {{"selected_other_resources": ["Key1", ...]}}
    """

    try:
        from .llm_requirements import get_llm
        fresh_llm = get_llm()
        response = fresh_llm.invoke(prompt)
        raw_output = response.content.strip()
        clean_json = re.sub(r'^```json\s*|```$', '', raw_output, flags=re.MULTILINE).strip()
        data = _json.loads(clean_json)
        clinical_artifact = "InsurancePlanBundle"
        must_resources = _nhcx_get_must_resources(clinical_artifact)
        selected_other_resources = [
            r for r in data.get("selected_other_resources", []) if r not in must_resources
        ]
        print(f"NHCX Artifact: {clinical_artifact} | Other: {selected_other_resources}")
        return clinical_artifact, must_resources, selected_other_resources
    except Exception as e:
        print(f"select_nhcx_resources parse error: {e}")
        return "InsurancePlanBundle", _nhcx_get_must_resources("InsurancePlanBundle"), []


def distill_insurance_text(full_text):
    """
    Distil insurance policy text into a high-density fact sheet for FHIR extraction.

    Optimisations vs original:
    - Chunks reduced 8 → 4  (Gemma 4 handles larger context comfortably)
    - Chunks processed in parallel with ThreadPoolExecutor (max 4 workers)
    - Serial 8-call latency (~8–12 min) → parallel 4-call latency (~60–90 s)
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
        "ACT AS an Insurance Policy Underwriter. Simplify this policy text into a high-density Fact Sheet.\n"
        "RULES: Capture ALL numerics, preserve tables as Markdown, no filler words, keep insurance terms.\n"
        "TEXT: {chunk_text}\n"
        "OUTPUT: Condensed facts only. If no insurance data present, return: [NO_INSURANCE_DATA]"
    )

    print(f"Distilling {total_len} chars across {num_chunks} chunks (parallel)...")

    def _process_chunk(args):
        i, chunk = args
        try:
            from .llm_requirements import get_llm
            llm = get_llm()  # uses cached client
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

    # Reconstruct in original chunk order
    distilled_outputs = [results[i] for i in sorted(results.keys())]
    final = "\n\n".join(distilled_outputs)
    print(f"Distillation done. Original: {total_len} chars → Distilled: {len(final)} chars")
    return final



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
