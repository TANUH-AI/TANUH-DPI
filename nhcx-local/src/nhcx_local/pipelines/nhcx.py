"""
nhcx.py -- NHCX Insurance Document Pipeline (local version).

Processes insurance PDFs (Insurance Plans, Claims) into FHIR R4 Bundles
using a local LLM via Ollama.

Pipeline: OCR -> Distill -> Classify -> LangGraph Workflow -> FHIR Bundle Assembly -> Local JSON output
"""

import json
import math
import os
import re
import uuid
import operator
import logging
from typing import TypedDict, List, Dict, Annotated, Any
from datetime import datetime, timezone

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
    id_registry: Dict[str, Any]
    final_resources: Annotated[List[dict], operator.add]
    rulebook_paths: Dict[str, str]
    model: str


# ── Resource Dependencies ────────────────────────────────────────────────────

RESOURCE_DEPENDENCIES = {
    "Organization": [],
    "Binary": [],
    "DocumentReference": ["Binary"],
    "InsurancePlan": ["Organization"],
    "HealthcareService": ["InsurancePlan"],
    "InsurancePlanBundle": ["InsurancePlan", "Organization"],
}

NHCX_EXTRACTION_DICTIONARY = {
    "NHCXArtifact": {
        "InsurancePlanBundle": "Bundle of type collection describing a health insurance package.",
    },
    "OtherResources": {
        "InsurancePlan": "Health insurance product/plan provided by an organization.",
        "Claim": "Provider-issued list of professional services for reimbursement.",
        "ClaimResponse": "Adjudication results from a payer in response to a Claim.",
        "Coverage": "Insurance plan details for a patient.",
        "CoverageEligibilityRequest": "Check if patient has insurance coverage.",
        "CoverageEligibilityResponse": "Payer response providing eligibility and plan details.",
        "Task": "Payments, status checks during claim adjudication.",
        "Communication": "Exchange of information between sender and receiver.",
        "CommunicationRequest": "Request for communication (e.g., requesting documents).",
        "PaymentNotice": "Notification that payment has been made.",
        "PaymentReconciliation": "Reconcile a bulk payment against multiple claims.",
        "Organization": "Healthcare organizations, insurers, or TPAs.",
        "Patient": "Basic demographics of individual beneficiary.",
        "Practitioner": "Healthcare professional demographics.",
        "PractitionerRole": "Roles of a practitioner within an organization.",
        "Condition": "Conditions/diagnoses (used to justify medical necessity).",
        "Procedure": "Clinical procedures mapped to claim line items.",
        "DocumentReference": "Reference to supporting documents.",
        "Binary": "Raw digital content (scanned PDF, brochure).",
    }
}


def get_must_resources(artifact):
    if artifact == "InsurancePlanBundle":
        return ["InsurancePlanBundle", "InsurancePlan", "Organization", "Condition", "DocumentReference"]
    return []


# ── Insurance Text Distillation ──────────────────────────────────────────────

def distill_insurance_text(full_text: str, model: str = None) -> str:
    """Distill raw OCR text into high-density insurance fact sheet."""
    num_chunks = 8
    overlap_size = 2000

    total_len = len(full_text)
    chunk_size = math.ceil(total_len / num_chunks)

    chunks = []
    for i in range(num_chunks):
        start = max(0, i * chunk_size - overlap_size)
        end = min(total_len, (i + 1) * chunk_size)
        chunks.append(full_text[start:end])

    distilled_outputs = []

    distill_prompt_template = """
    ACT AS an Insurance Policy Underwriter. Your goal is to simplify this policy text into a high-density "Fact Sheet" for a FHIR Architect.

    TASK:
    Scan the text below and extract EVERY technical detail related to insurance policy parameters.

    STRICT EXTRACTION RULES:
    1. CAPTURE ALL NUMERICS: Every INR value, Percentage (%), Day limit, or Age limit must be preserved.
    2. PRESERVE TABLES: If you find a benefit table or a list of limits, recreate it as a Markdown Table.
    3. NO NARRATIVE: Do not use filler words. Just state the facts.
    4. NO "NOT SPECIFIED": If a specific category isn't there, simply MOVE ON.
    5. TERMINOLOGY: Keep specific medical/insurance terms.
    6. INSURANCE PLAN DETAILS: Don't miss details about the insurance plan, covered benefits, costs, and limits.

    TEXT CONTENT:
    {chunk_text}

    OUTPUT:
    Provide a condensed version of the relevant data found above. If the text is purely legal preamble with no specific limits or benefits, return: [NO_INSURANCE_DATA]
    """

    logger.info(f"Distilling {total_len} characters in {num_chunks} chunks...")

    for i, chunk in enumerate(chunks):
        logger.info(f"Processing section {i+1}/{num_chunks}...")
        try:
            fresh_llm = get_llm(model=model)
            response = fresh_llm.invoke([HumanMessage(content=distill_prompt_template.format(chunk_text=chunk))])
            content = response.content.strip()
            if "[NO_INSURANCE_DATA]" not in content:
                distilled_outputs.append(f"### SECTION {i+1} SUMMARY ###\n{content}")
        except Exception as e:
            logger.error(f"Error in section {i+1}: {e}")

    final_distilled_text = "\n\n".join(distilled_outputs)
    logger.info(f"Distillation complete. Original: {total_len} chars | Distilled: {len(final_distilled_text)} chars")
    return final_distilled_text


# ── Resource Selection ───────────────────────────────────────────────────────

def select_nhcx_resources(distilled_text: str, model: str = None):
    """Select relevant NHCX FHIR resources based on distilled text."""
    prompt = f"""
    ACT AS an expert NHCX FHIR Data Architect.

    **TASK:**
    Identify and select relevant FHIR resources from OtherResources based ONLY on the information in the text.

    **RULES:**
    1. Only select a resource if the text contains specific data points for it.
    2. DO NOT select resources already part of the Mandatory Base (InsurancePlan, Organization).
    3. If text mentions "Diagnosis" -> select Condition. "Surgery" -> select Procedure.

    **INPUT:**
    [Extracted Text]:
    {distilled_text}

    [Dictionary]:
    {json.dumps(NHCX_EXTRACTION_DICTIONARY, indent=2)}

    **OUTPUT FORMAT:**
    Return ONLY a valid JSON object. No pre-amble or markdown blocks.
    {{
        "selected_other_resources": ["Key1", "Key2", ...]
    }}
    """

    try:
        fresh_llm = get_llm(model=model)
        response = fresh_llm.invoke(prompt)
        raw_output = response.content.strip()
        clean_json = re.sub(r'^```json\s*|```$', '', raw_output, flags=re.MULTILINE).strip()
        data = json.loads(clean_json)

        clinical_artifact = "InsurancePlanBundle"
        must_resources = get_must_resources(clinical_artifact)
        selected_other_resources = data.get("selected_other_resources", [])
        selected_other_resources = [res for res in selected_other_resources if res not in must_resources]

        logger.info(f"Artifact: {clinical_artifact} | Must: {must_resources} | Other: {selected_other_resources}")
    except Exception as e:
        logger.warning(f"LLM resource selection failed: {e}")
        clinical_artifact = "InsurancePlanBundle"
        must_resources = get_must_resources(clinical_artifact)
        selected_other_resources = []

    return clinical_artifact, must_resources, selected_other_resources


# ── Core Extraction Agent ────────────────────────────────────────────────────

def run_extraction_agent(state: AgentState, resource_type: str):
    rulebook_path = state['rulebook_paths'].get(resource_type)
    rulebook_content = ""
    if rulebook_path and os.path.exists(rulebook_path):
        with open(rulebook_path, 'r', encoding='utf-8') as f:
            rulebook_content = f.read()

    prompt = f'''
    ACT AS an expert NHCX FHIR Data Architect.

EXTRACT ONLY a valid HL7 FHIR R4 {resource_type} resource (or a Bundle containing multiple resources) from the provided technical insurance text.

RULEBOOK (STRUCTURE GUIDANCE):
{rulebook_content}

INSURANCE POLICY TEXT (DISTILLED):
{state["text"]}

STRICT REQUIREMENTS (NON-NEGOTIABLE):
* Output MUST be valid JSON only.
* Output MUST start with "{{" or "[".
* DO NOT output markdown code fences, no preamble, no comments, and no explanations.
* DO NOT hallucinate or infer missing data.
* Extract ONLY information explicitly present in the provided text.
* Omit any field whose value is not clearly present.

NHCX + ABDM CONSTRAINTS:
* Conform to NHCX (National Health Claims Exchange) and ABDM profiling expectations.
* Every resource MUST contain an "id" as a UUID string (RFC-4122 format).
* Use the Product UIN as the business identifier for InsurancePlan.
* DO NOT include empty objects, empty arrays, or null values.

TERMINOLOGY & CODING RULES:
* Use IRDAI Standard Exclusion Codes for exclusions.
* Use SNOMED CT for clinical conditions if coding is required.
* NEVER fabricate codes.

REFERENCE & LINKING RULES:
* Use URN UUID references: "reference": "urn:uuid:<uuid-here>".
* InsurancePlan MUST reference Organization via .ownedBy.
* Only create references explicitly justified by the text.

DATA ACCURACY RULES:
* Preserve numeric precision exactly.
* Preserve all currency values (INR) and time-based limits exactly.

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

def create_insurance_node(resource_type: str):
    if resource_type in _node_cache:
        return _node_cache[resource_type]

    def node(state: AgentState):
        if resource_type == "InsurancePlanBundle":
            actual_resource_type = "Bundle"
            is_insurance_bundle = True
        else:
            actual_resource_type = resource_type
            is_insurance_bundle = False

        resources = run_extraction_agent(state, actual_resource_type)
        resources = normalize_resource_output(resources, actual_resource_type)

        if isinstance(resources, list):
            safe_resources = []
            max_items = 1 if is_insurance_bundle else 15
            for res in resources[:max_items]:
                if isinstance(res, dict):
                    if res.get("resourceType") != actual_resource_type:
                        res["resourceType"] = actual_resource_type
                    if is_insurance_bundle:
                        res.setdefault('meta', {})['profile'] = [
                            "https://nrces.in/ndhm/fhir/r4/StructureDefinition/InsurancePlanBundle"
                        ]
                        res['type'] = 'collection'
                    res = ensure_id(res)
                    payer_id = state['id_registry'].get('organization_id')
                    if payer_id and resource_type == "InsurancePlan":
                        res['ownedBy'] = {'reference': f'urn:uuid:{payer_id}'}
                    safe_resources.append(res)
            result = safe_resources
        else:
            result = get_single_resource([resources], actual_resource_type)
            result = ensure_id(result)
            if is_insurance_bundle:
                result.setdefault('meta', {})['profile'] = [
                    "https://nrces.in/ndhm/fhir/r4/StructureDefinition/InsurancePlanBundle"
                ]
                result['type'] = 'collection'
            payer_id = state['id_registry'].get('organization_id')
            if payer_id and resource_type == "InsurancePlan":
                result['ownedBy'] = {'reference': f'urn:uuid:{payer_id}'}

        if isinstance(result, list):
            state['id_registry'][f'{resource_type.lower()}_refs'] = [
                {'reference': f'urn:uuid:{r["id"]}'} for r in result
            ]
            if resource_type == "Organization" and len(result) > 0:
                state['id_registry']['organization_id'] = result[0]['id']
        else:
            state['id_registry'][f'{resource_type.lower()}_id'] = result['id']
            if resource_type == "Organization":
                state['id_registry']['organization_id'] = result['id']

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

def insurance_assembly_node(state):
    bundle = {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "meta": {"profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/InsurancePlanBundle"]},
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry": []
    }

    # InsurancePlan FIRST
    plan_found = False
    seen_ids = set()

    for resources_list in state["final_resources"]:
        if isinstance(resources_list, list):
            for res in resources_list:
                if isinstance(res, dict) and res.get('resourceType') == 'InsurancePlan':
                    bundle["entry"].insert(0, {"fullUrl": f"urn:uuid:{res['id']}", "resource": res})
                    seen_ids.add(res['id'])
                    plan_found = True
                    break
        if plan_found:
            break

    supporting_entries = []
    attachment_entries = []

    for resources_list in state["final_resources"]:
        if not isinstance(resources_list, list):
            resources_list = [resources_list]
        for r in resources_list:
            if not isinstance(r, dict) or r.get('id') in seen_ids:
                continue
            resource_type = r.get('resourceType')
            entry = {"fullUrl": f"urn:uuid:{r['id']}", "resource": r}
            if resource_type in ['DocumentReference', 'Binary']:
                attachment_entries.append(entry)
            else:
                supporting_entries.append(entry)
            seen_ids.add(r['id'])

    bundle["entry"].extend(supporting_entries)
    bundle["entry"].extend(attachment_entries)

    logger.info(f"NHCX Bundle assembled: {len(bundle['entry'])} total resources")
    return {"final_resources": [bundle]}


# ── Workflow Builder ─────────────────────────────────────────────────────────

def build_insurance_workflow(clinical_artifact: str, selected_other_resources: List[str], rulebook_paths: Dict[str, str]):
    must_resources = get_must_resources(clinical_artifact)
    selected_other_resources = [res for res in selected_other_resources if res not in must_resources]
    all_resources = list(set(must_resources + selected_other_resources))
    if clinical_artifact not in all_resources:
        all_resources.append(clinical_artifact)

    workflow = StateGraph(AgentState)

    created_nodes = set()
    for resource in all_resources:
        node_name = resource.lower()
        if node_name not in created_nodes:
            node_func = create_insurance_node(resource)
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
        workflow.add_edge(current, next_node)

    workflow.add_node("assembly", insurance_assembly_node)
    last_node = resource_order[-1].lower()
    workflow.add_edge(last_node, "assembly")
    workflow.add_edge("assembly", END)

    if "organization" in created_nodes:
        workflow.set_entry_point("organization")
    else:
        workflow.set_entry_point(resource_order[0].lower())

    return workflow.compile(), all_resources


# ── Main Pipeline Function ───────────────────────────────────────────────────

def run_nhcx_pipeline(distilled_text: str, clinical_artifact: str,
                      selected_other_resources: List[str],
                      rulebook_dir: str, pdf_base64: str = None,
                      idx: int = 0, model: str = None):
    """
    Run the full NHCX extraction pipeline and return a FHIR Bundle dict.

    Args:
        distilled_text:           Distilled insurance text.
        clinical_artifact:        "InsurancePlanBundle".
        selected_other_resources: List of additional FHIR resources to extract.
        rulebook_dir:             Path to directory containing StructureDefinition JSONs.
        pdf_base64:               Base64-encoded PDF for embedding in DocumentReference.
        idx:                      Patient index.
        model:                    Ollama model name.

    Returns:
        FHIR Bundle dict.
    """
    clear_node_cache()

    rulebook_paths = {
        "Organization": os.path.join(rulebook_dir, "StructureDefinition-Organization_updated.json"),
        "InsurancePlan": os.path.join(rulebook_dir, "StructureDefinition-InsurancePlan_updated.json"),
        "InsurancePlanBundle": os.path.join(rulebook_dir, "StructureDefinition-InsurancePlanBundle_updated.json"),
    }
    for res in selected_other_resources:
        path = os.path.join(rulebook_dir, f"StructureDefinition-{res}_updated.json")
        if os.path.exists(path):
            rulebook_paths[res] = path

    initial_state = {
        "text": distilled_text,
        "clinical_artifact": clinical_artifact,
        "id_registry": {},
        "final_resources": [],
        "rulebook_paths": rulebook_paths,
        "model": model,
    }

    app, used_resources = build_insurance_workflow(clinical_artifact, selected_other_resources, rulebook_paths)

    logger.info(f"Starting NHCX FHIR Bundle generation...")
    final_output = app.invoke(initial_state)
    bundle = final_output['final_resources'][-1]

    bundle = clean_and_reorder_bundle(bundle)
    if pdf_base64:
        bundle = embed_pdf_in_document_reference(bundle, pdf_base64=pdf_base64)

    logger.info(f"NHCX FHIR Bundle generated: {len(bundle.get('entry', []))} entries")
    return bundle
