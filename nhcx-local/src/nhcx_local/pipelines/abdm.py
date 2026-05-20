"""
abdm.py -- ABDM Clinical Document Pipeline (local version).

Processes clinical PDFs (Discharge Summaries, Diagnostic Reports)
into FHIR R4 Bundles using a local LLM via Ollama.

Pipeline: OCR -> Classify -> LangGraph Workflow -> FHIR Bundle Assembly -> Local JSON output
"""

import json
import os
import re
import uuid
import operator
import base64
import logging
from typing import TypedDict, List, Dict, Annotated, Any
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from nhcx_local.llm import get_llm
from nhcx_local.fhir_utils import (
    extract_json, ensure_id, normalize_resource_output,
    get_single_resource, clean_and_reorder_bundle,
    embed_pdf_in_document_reference,
)

logger = logging.getLogger(__name__)


# ── State ────────────────────────────────────────────────────────────────────

class AgentState(TypedDict, total=False):
    text: str
    clinical_artifact: str
    id_registry: Dict[str, Any]
    final_resources: Annotated[List[dict], operator.add]
    rulebook_paths: Dict[str, str]
    model: str


# ── Resource Dependencies ────────────────────────────────────────────────────

RESOURCE_DEPENDENCIES = {
    "Patient": [],
    "Organization": [],
    "Practitioner": ["Patient"],
    "PractitionerRole": ["Patient", "Practitioner", "Organization"],
    "Encounter": ["Patient", "Practitioner", "PractitionerRole", "Organization"],
    "Observation": ["Patient", "Encounter"],
    "ObservationVitalSigns": ["Patient", "Encounter"],
    "ObservationBodyMeasurement": ["Patient", "Encounter"],
    "Condition": ["Patient", "Encounter"],
    "Procedure": ["Patient", "Encounter", "Practitioner"],
    "DiagnosticReportLab": ["Patient", "Practitioner", "Observation"],
    "DiagnosticReportImaging": ["Patient", "Practitioner", "Observation"],
    "MedicationRequest": ["Patient", "Practitioner"],
    "MedicationStatement": ["Patient"],
    "Medication": ["Patient"],
    "AllergyIntolerance": ["Patient"],
    "DocumentReference": ["Patient"],
    "DischargeSummaryRecord": ["Patient", "Encounter"],
    "DiagnosticReportRecord": ["Patient", "DiagnosticReportLab"],
}

ABDM_EXTRACTION_DICTIONARY = {
    "ClinicalArtifacts": {
        "DischargeSummaryRecord": "A Clinical document used to represent the discharge summary record for ABDM HDE data set.",
        "DiagnosticReportRecord": "A Clinical Artifact representing diagnostic reports, including Radiology and Laboratory reports.",
    },
    "OtherResources": {
        "Patient": "Patient resource for basic demographics.",
        "Practitioner": "Practitioner resource for healthcare provider info.",
        "PractitionerRole": "Practitioner role within an organization.",
        "Organization": "Healthcare organization info.",
        "Encounter": "Encounter information (inpatient/outpatient).",
        "Condition": "Conditions, problems, or diagnoses.",
        "Procedure": "Clinical procedures performed.",
        "Observation": "Laboratory test results and findings.",
        "DiagnosticReportLab": "Laboratory diagnosis report (CBC, Lipid Panel, etc.).",
        "DiagnosticReportImaging": "Imaging diagnosis report (Radiology, Cardiology, etc.).",
        "ObservationVitalSigns": "Vital signs (Blood Pressure, Heart Rate, etc.).",
        "ObservationBodyMeasurement": "Physical metrics (Weight, Height, BMI).",
        "ObservationGeneralAssessment": "General health assessment scores.",
        "ObservationLifestyle": "Lifestyle details (smoking, alcohol status).",
        "ObservationPhysicalActivity": "Physical activity levels.",
        "ObservationWomenHealth": "Obstetric/gynecological history.",
        "MedicationRequest": "Medication prescriptions/orders.",
        "MedicationStatement": "Medication information (past, present, future).",
        "Medication": "Medicine details (ingredients, form).",
        "AllergyIntolerance": "Allergy/intolerance records.",
        "FamilyMemberHistory": "Significant health conditions of relatives.",
        "Immunization": "Immunization history.",
        "CarePlan": "Assessment and plan of treatment.",
        "ServiceRequest": "Requests for diagnostic investigations or referrals.",
        "Specimen": "Biological sample details.",
        "ImagingStudy": "DICOM imaging study content.",
        "DocumentReference": "Reference to patient documents.",
        "Binary": "Raw artifact (PDF, scanned image).",
        "Media": "Media like photo, video, or audio recording.",
    }
}


def get_must_resources(artifact):
    if artifact == "DiagnosticReportRecord":
        return ["DocumentBundle", "DiagnosticReportRecord", "Patient", "Practitioner",
                "Organization", "DiagnosticReportLab", "Observation", "DocumentReference"]
    elif artifact == "DischargeSummaryRecord":
        return ["DocumentBundle", "DischargeSummaryRecord", "Patient", "Encounter", "Practitioner",
                "Organization", "Condition", "Procedure", "Specimen", "Appointment",
                "Observation", "DocumentReference"]
    return []


# ── Patient Grouping (multi-patient lab PDFs) ────────────────────────────────

def extract_metadata(page_text):
    age_sex_match = re.search(r'Age/Sex\s*:\s*(.*)', page_text)
    age_sex = age_sex_match.group(1).strip() if age_sex_match else "UNKNOWN"
    collection_match = re.search(r'Collection Date\s*:\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4})', page_text)
    collection_date = collection_match.group(1) if collection_match else "UNKNOWN"
    return age_sex, collection_date


def is_lab_report_pdf(pages_text: list) -> bool:
    for page_text in pages_text:
        has_age_sex = bool(re.search(r'Age/Sex\s*:', page_text))
        has_collection_date = bool(re.search(r'Collection Date\s*:\s*[0-9]{2}-[A-Za-z]{3}-[0-9]{4}', page_text))
        if has_age_sex and has_collection_date:
            return True
    return False


def group_pages_by_patient(pages_text):
    grouped = defaultdict(list)
    for page_number, page_text in enumerate(pages_text, start=1):
        age_sex, collection_date = extract_metadata(page_text)
        fingerprint = f"{age_sex}_{collection_date}"
        grouped[fingerprint].append((page_number, page_text))

    final_patient_texts = []
    for key, page_data in grouped.items():
        merged_text = "\n\n".join([text for _, text in page_data])
        final_patient_texts.append(merged_text)
    return final_patient_texts


# ── Document Classification ──────────────────────────────────────────────────

def classify_document(text: str, model: str = None):
    """Classify clinical document type and select relevant FHIR resources."""
    prompt = f"""
    ACT AS an expert ABDM FHIR Data Architect.

    TASK:
    1. Analyze the [Extracted Text] and select the most appropriate key from [ClinicalArtifacts].
    2. Select any relevant keys from [RemainingResources] that are explicitly mentioned in the text.
    - DO NOT select resources that are already part of the Mandatory Base for your chosen artifact.

    INPUT:
    [Extracted Text]:
    {text}

    [Dictionary]:
    {json.dumps(ABDM_EXTRACTION_DICTIONARY, indent=2)}

    OUTPUT FORMAT:
    Return ONLY a valid JSON object. No pre-amble or markdown blocks.
    {{
        "clinical_artifact": "SelectedKeyFromClinicalArtifacts",
        "selected_other_resources": ["Key1", "Key2", ...]
    }}
    """

    clinical_artifact = ""
    must_resources = []
    selected_other_resources = []

    try:
        fresh_llm = get_llm(model=model)
        response = fresh_llm.invoke(prompt)
        raw_output = response.content.strip()

        clean_json = re.sub(r'^```json\s*|```$', '', raw_output, flags=re.MULTILINE).strip()
        data = json.loads(clean_json)

        clinical_artifact = data.get("clinical_artifact", "")
        must_resources = get_must_resources(clinical_artifact)
        selected_other_resources = data.get("selected_other_resources", [])
        selected_other_resources = [res for res in selected_other_resources if res not in must_resources]

        logger.info(f"Artifact: {clinical_artifact} | Must: {must_resources} | Other: {selected_other_resources}")

    except Exception as e:
        logger.warning(f"LLM classification failed: {e}, falling back to keywords")
        text_lower = text.lower()
        discharge_keywords = ["discharge", "admission", "course in hospital", "condition at discharge",
                              "hospital course", "chief complaint", "final diagnosis", "discharge diagnosis",
                              "date of admission", "date of discharge", "inpatient"]
        diagnostic_keywords = ["lab no", "collection date", "report date", "test name",
                               "reference range", "haemoglobin", "platelet", "radiology",
                               "impression", "x-ray", "mri", "ct scan", "ultrasound",
                               "laboratory", "pathology", "biopsy", "specimen"]

        discharge_score = sum(1 for kw in discharge_keywords if kw in text_lower)
        diagnostic_score = sum(1 for kw in diagnostic_keywords if kw in text_lower)

        clinical_artifact = "DischargeSummaryRecord" if discharge_score >= diagnostic_score else "DiagnosticReportRecord"
        must_resources = get_must_resources(clinical_artifact)
        selected_other_resources = []

    return clinical_artifact, must_resources, selected_other_resources


# ── Core Extraction Agent ────────────────────────────────────────────────────

def run_extraction_agent(state: AgentState, resource_type: str):
    """Run LLM extraction for a single FHIR resource type."""
    rulebook_path = state['rulebook_paths'].get(resource_type)
    rulebook_content = ""
    if rulebook_path and os.path.exists(rulebook_path):
        with open(rulebook_path, 'r', encoding='utf-8') as f:
            rulebook_content = f.read()

    prompt = f'''
    Extract ONLY a valid HL7 FHIR R4 {resource_type} resource (or array of resources) from the clinical text.

RULEBOOK (ADDITIONAL STRUCTURE GUIDANCE):
{rulebook_content}

CLINICAL TEXT:
{state["text"]}

STRICT REQUIREMENTS (NON-NEGOTIABLE):

* Output MUST be valid JSON only
* Output MUST start with "{{" or "["
* DO NOT output markdown, comments, explanations, or code fences
* DO NOT hallucinate or infer missing data
* Extract ONLY information explicitly present in the clinical text
* Omit any field whose value is not clearly present

FHIR + ABDM CONSTRAINTS:

* Conform to HL7 FHIR R4 structure
* Conform to ABDM / NDHM profiling expectations
* Include "resourceType" correctly
* Every resource MUST contain an "id"
* "id" MUST be a UUID string (RFC-4122 format)
* Use only fields relevant to {resource_type}
* DO NOT include empty objects or empty arrays
* DO NOT include null values

TERMINOLOGY RULES:

* Clinical concepts -> SNOMED CT codes when applicable
* Laboratory / measurements -> LOINC codes when applicable
* Units -> UCUM codes
* Include proper system URLs:
  SNOMED CT -> http://snomed.info/sct
  LOINC -> http://loinc.org
  UCUM -> http://unitsofmeasure.org
* If no explicit coded value exists in text -> use only "text" representation
* NEVER fabricate codes

REFERENCE & LINKING RULES:

* Use URN UUID references when linking resources: "reference": "urn:uuid:<resource-id>"
* Only create references that are explicitly justified by the text
* DO NOT create imaginary relationships

DATA ACCURACY RULES:

* Preserve original clinical meaning
* Preserve numeric precision exactly
* Preserve dates exactly as written
* DO NOT normalize, reinterpret, or guess

OUTPUT FORMAT:

Return ONLY the JSON resource(s) for {resource_type}.
'''

    try:
        fresh_llm = get_llm(model=state.get('model'))
        response = fresh_llm.invoke([HumanMessage(content=prompt)])
        raw_output = response.content.strip()
        logger.info(f"Raw output for {resource_type}: {raw_output[:200]}...")

        parsed = extract_json(raw_output)
        if parsed:
            return parsed

        logger.warning(f"Could not parse JSON for {resource_type}")
    except Exception as e:
        logger.error(f"Error for {resource_type}: {e}")

    return [{"resourceType": resource_type, "id": str(uuid.uuid4()),
             "meta": {"profile": [f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/{resource_type}"]}}]


# ── Node Factory ─────────────────────────────────────────────────────────────

_node_cache = {}

def create_resource_node(resource_type: str):
    if resource_type in _node_cache:
        return _node_cache[resource_type]

    def node(state: AgentState):
        if resource_type in ["DiagnosticReportRecord", "DischargeSummaryRecord"]:
            actual_resource_type = "Composition"
            is_composition = True
        else:
            actual_resource_type = resource_type
            is_composition = False

        resources = run_extraction_agent(state, actual_resource_type)
        resources = normalize_resource_output(resources, actual_resource_type)

        if isinstance(resources, list):
            safe_resources = []
            max_items = 1 if is_composition else 100
            for res in resources[:max_items]:
                if isinstance(res, dict):
                    if res.get("resourceType") != actual_resource_type:
                        res["resourceType"] = actual_resource_type
                    if is_composition:
                        res.setdefault('meta', {})['profile'] = [
                            f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/{resource_type}"
                        ]
                    res = ensure_id(res)
                    patient_id = state['id_registry'].get('patient_id')
                    if patient_id and 'subject' in res:
                        res['subject'] = {'reference': f'urn:uuid:{patient_id}'}
                    safe_resources.append(res)
            result = safe_resources
        else:
            result = get_single_resource([resources], actual_resource_type)
            result = ensure_id(result)
            if is_composition:
                result.setdefault('meta', {})['profile'] = [
                    f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/{resource_type}"
                ]
            patient_id = state['id_registry'].get('patient_id')
            if patient_id and 'subject' in result:
                result['subject'] = {'reference': f'urn:uuid:{patient_id}'}

        if isinstance(result, list):
            state['id_registry'][f'{resource_type.lower()}_refs'] = [
                {'reference': f'urn:uuid:{r["id"]}'} for r in result
            ]
        else:
            state['id_registry'][f'{resource_type.lower()}_id'] = result['id']

        count = len(result) if isinstance(result, list) else 1
        logger.info(f"{resource_type}: {count} resource(s) extracted")
        return {"final_resources": [result] if isinstance(result, list) else [result]}

    node.__name__ = f"{resource_type.lower()}_node"
    _node_cache[resource_type] = node
    return node


def clear_node_cache():
    global _node_cache
    _node_cache = {}


# ── Assembly Node ────────────────────────────────────────────────────────────

def assembly_node(state):
    bundle = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "meta": {"profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/DocumentBundle"]},
        "type": "document",
        "identifier": {"system": "https://www.abdm.gov.in/bundle", "value": str(uuid.uuid4())},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry": []
    }

    clinical_artifact = state.get('clinical_artifact')

    # Add Composition FIRST
    composition_found = False
    for resources in state["final_resources"]:
        if isinstance(resources, list):
            for comp in resources:
                if (comp.get('resourceType') == 'Composition' and
                    clinical_artifact in [p.split('/')[-1] for p in comp.get('meta', {}).get('profile', [])]):
                    bundle["entry"].insert(0, {"fullUrl": f"urn:uuid:{comp['id']}", "resource": comp})
                    composition_found = True
                    break
            if composition_found:
                break

    seen_ids = {entry['resource']['id'] for entry in bundle["entry"]}
    doc_refs = []

    for resources in state["final_resources"]:
        if isinstance(resources, list):
            for r in resources:
                if isinstance(r, dict) and r.get('resourceType') == 'DocumentReference' and r.get('id') not in seen_ids:
                    doc_refs.append(r)
        elif isinstance(resources, dict) and resources.get('resourceType') == 'DocumentReference' and resources.get('id') not in seen_ids:
            doc_refs.append(resources)

    for resources in state["final_resources"]:
        if isinstance(resources, list):
            for r in resources:
                if isinstance(r, dict) and r.get('id') not in seen_ids and r.get('resourceType') != 'DocumentReference':
                    seen_ids.add(r['id'])
                    bundle["entry"].append({"fullUrl": f"urn:uuid:{r['id']}", "resource": r})
        elif isinstance(resources, dict) and resources.get('id') not in seen_ids and resources.get('resourceType') != 'DocumentReference':
            seen_ids.add(resources['id'])
            bundle["entry"].append({"fullUrl": f"urn:uuid:{resources['id']}", "resource": resources})

    for doc_ref in doc_refs:
        seen_ids.add(doc_ref['id'])
        bundle["entry"].append({"fullUrl": f"urn:uuid:{doc_ref['id']}", "resource": doc_ref})

    return {"final_resources": [bundle]}


# ── Workflow Builder ─────────────────────────────────────────────────────────

def build_dynamic_workflow(clinical_artifact: str, selected_other_resources: List[str], rulebook_paths: Dict[str, str]):
    must_resources = get_must_resources(clinical_artifact)
    selected_other_resources = [res for res in selected_other_resources if res not in must_resources]
    all_resources = list(set(must_resources + selected_other_resources))
    all_resources.append(clinical_artifact)

    workflow = StateGraph(AgentState)

    created_nodes = set()
    for resource in all_resources:
        node_name = resource.lower()
        if node_name not in created_nodes:
            node_func = create_resource_node(resource)
            workflow.add_node(node_name, node_func)
            created_nodes.add(node_name)

    def topological_sort(resources):
        visited = set()
        order = []
        def visit(resource):
            if resource in visited:
                return
            visited.add(resource)
            for dep in RESOURCE_DEPENDENCIES.get(resource, []):
                if dep in resources:
                    visit(dep)
            order.append(resource)
        for resource in resources:
            visit(resource)
        return order

    resource_order = topological_sort(all_resources)

    for i in range(len(resource_order) - 1):
        current = resource_order[i].lower()
        next_node = resource_order[i + 1].lower()
        if current in workflow.nodes and next_node in workflow.nodes:
            workflow.add_edge(current, next_node)

    workflow.add_node("assembly", assembly_node)
    last_node = resource_order[-1].lower()
    if last_node in workflow.nodes:
        workflow.add_edge(last_node, "assembly")
    workflow.add_edge("assembly", END)

    if "patient" in workflow.nodes:
        workflow.set_entry_point("patient")

    return workflow.compile(), all_resources


# ── Main Pipeline Function ───────────────────────────────────────────────────

def run_abdm_pipeline(extracted_text: str, clinical_artifact: str,
                      selected_other_resources: List[str],
                      rulebook_dir: str, pdf_base64: str = None,
                      idx: int = 0, model: str = None):
    """
    Run the full ABDM extraction pipeline and return a FHIR Bundle dict.

    Args:
        extracted_text:           OCR-extracted text from the PDF.
        clinical_artifact:        "DischargeSummaryRecord" or "DiagnosticReportRecord".
        selected_other_resources: List of additional FHIR resources to extract.
        rulebook_dir:             Path to directory containing StructureDefinition JSONs.
        pdf_base64:               Base64-encoded PDF for embedding in DocumentReference.
        idx:                      Patient index (for multi-patient PDFs).
        model:                    Ollama model name.

    Returns:
        FHIR Bundle dict.
    """
    clear_node_cache()

    rulebook_paths = {}
    for res in ABDM_EXTRACTION_DICTIONARY["OtherResources"]:
        path = os.path.join(rulebook_dir, f"StructureDefinition-{res}_updated.json")
        if os.path.exists(path):
            rulebook_paths[res] = path

    initial_state = {
        "text": extracted_text,
        "clinical_artifact": clinical_artifact,
        "id_registry": {},
        "final_resources": [],
        "rulebook_paths": rulebook_paths,
        "model": model,
    }

    app, used_resources = build_dynamic_workflow(clinical_artifact, selected_other_resources, rulebook_paths)

    logger.info(f"Starting FHIR Bundle generation for patient {idx}...")
    final_output = app.invoke(initial_state)
    bundle = final_output['final_resources'][-1]

    bundle = clean_and_reorder_bundle(bundle)
    if pdf_base64:
        bundle = embed_pdf_in_document_reference(bundle, pdf_base64=pdf_base64)

    logger.info(f"FHIR Bundle generated: {len(bundle.get('entry', []))} entries")
    return bundle
