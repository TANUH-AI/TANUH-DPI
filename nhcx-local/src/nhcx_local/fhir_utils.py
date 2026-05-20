"""
fhir_utils.py -- Shared FHIR utilities: JSON extraction, sanitisation, bundle reordering.

These functions are used by both the ABDM and NHCX pipelines.
"""

import json
import uuid
import re
from datetime import datetime, timezone


# ── JSON Extraction ──────────────────────────────────────────────────────────

def extract_json(text: str):
    """Extract first valid JSON object or array from LLM output text."""
    if not text or not text.strip():
        return None

    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        try:
            obj, end = decoder.raw_decode(text[idx:])
            if isinstance(obj, str):
                try:
                    obj = json.loads(obj)
                except Exception:
                    pass
            return obj
        except json.JSONDecodeError:
            idx += 1
    return None


# ── Resource Normalisation ───────────────────────────────────────────────────

def ensure_id(resource):
    """Ensure resource has a UUID id."""
    if not isinstance(resource, dict):
        return resource
    if "id" not in resource or not resource["id"]:
        resource["id"] = str(uuid.uuid4())
    return resource


def normalize_resource_output(res, resource_type):
    """Convert any input to list of dicts."""
    if isinstance(res, str):
        parsed = extract_json(res)
        if parsed:
            res = parsed

    if isinstance(res, dict):
        return [res]
    elif isinstance(res, list):
        return res
    else:
        return [{
            "resourceType": resource_type,
            "id": str(uuid.uuid4()),
            "meta": {"profile": [f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/{resource_type}"]}
        }]


def get_single_resource(resources_list, resource_type):
    """Get first valid resource from list."""
    for res in resources_list:
        if isinstance(res, dict) and res.get("resourceType") == resource_type:
            return res
    if resources_list:
        res = resources_list
        if isinstance(res, dict):
            res["resourceType"] = resource_type
            return res
    return {
        "resourceType": resource_type,
        "id": str(uuid.uuid4()),
        "meta": {"profile": [f"https://nrces.in/ndhm/fhir/r4/StructureDefinition/{resource_type}"]}
    }


# ── FHIR Sanitisation ───────────────────────────────────────────────────────

def sanitize_fhir_resource(resource):
    """Clean up common LLM hallucinations in FHIR resources."""
    res_type = resource.get("resourceType")
    if not res_type:
        return

    if res_type == "Bundle":
        for entry in resource.get("entry", []):
            if "resource" in entry:
                sanitize_fhir_resource(entry["resource"])
        return

    if "contained" in resource and isinstance(resource["contained"], list):
        for contained_res in resource["contained"]:
            sanitize_fhir_resource(contained_res)

    # 'entry' is ONLY valid on Bundle
    if res_type != "Bundle" and "entry" in resource:
        del resource["entry"]

    # Remove hallucinated fields
    for field in ["entity", "permission"]:
        if field in resource:
            del resource[field]

    # 'type' formatting for Organization and InsurancePlan
    if res_type in ["Organization", "InsurancePlan"] and "type" in resource:
        system_url = (
            "http://terminology.hl7.org/CodeSystem/organization-type"
            if res_type == "Organization"
            else "http://terminology.hl7.org/CodeSystem/insurance-plan-type"
        )
        if isinstance(resource["type"], str):
            code = "pay" if res_type == "Organization" else "medical"
            resource["type"] = [{"coding": [{"system": system_url, "code": code, "display": resource["type"]}]}]
        elif isinstance(resource["type"], dict):
            resource["type"] = [resource["type"]]
        elif isinstance(resource["type"], list):
            for t in resource["type"]:
                if "coding" in t and isinstance(t["coding"], list):
                    for c in t["coding"]:
                        if res_type == "Organization" and c.get("code") == "insurance":
                            c["code"] = "pay"
                            c["system"] = system_url
                        elif res_type == "InsurancePlan" and c.get("code") == "medical":
                            c["system"] = system_url

    if res_type == "DocumentReference":
        if resource.get("status") not in ["current", "superseded", "entered-in-error"]:
            resource["status"] = "current"
        if "type" in resource and isinstance(resource["type"], list):
            resource["type"] = resource["type"][0] if len(resource["type"]) > 0 else {}

    if res_type == "InsurancePlan" and "ownedBy" in resource:
        if isinstance(resource["ownedBy"], list):
            resource["ownedBy"] = resource["ownedBy"][0] if len(resource["ownedBy"]) > 0 else {}

    # Clean up InsurancePlan hallucinations
    if res_type == "InsurancePlan":
        for field in ["benefit", "exclusion", "note"]:
            if field in resource:
                del resource[field]
        for cov in resource.get("coverage", []):
            if "description" in cov:
                del cov["description"]
            if "type" not in cov:
                cov["type"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/insurance-plan-type", "code": "medical"}]}
            if "benefit" not in cov or not isinstance(cov["benefit"], list) or len(cov["benefit"]) == 0:
                cov["benefit"] = [{"type": {"coding": [{"code": "benefit"}]}}]
            if isinstance(cov["benefit"], list):
                for ben in cov["benefit"]:
                    for field in ["limit", "description"]:
                        if field in ben:
                            del ben[field]
        if "identifier" in resource and isinstance(resource["identifier"], list):
            for ident in resource["identifier"]:
                if ident.get("system") == "uin":
                    ident["system"] = "https://irdai.gov.in/uin"

    # Fix missing required fields
    if res_type == "Procedure":
        if "status" not in resource:
            resource["status"] = "completed"
        if "subject" not in resource:
            resource["subject"] = {"display": "Unknown Patient"}

    if res_type == "ImagingStudy":
        if resource.get("status") not in ["registered", "available", "cancelled", "entered-in-error", "unknown"]:
            resource["status"] = "available"

    if res_type == "Coverage":
        if "status" not in resource:
            resource["status"] = "active"
        if "beneficiary" not in resource:
            resource["beneficiary"] = {"display": "Unknown Patient"}
        if "payor" not in resource:
            resource["payor"] = [{"display": "Unknown Organization"}]

    if res_type in ["Organization", "InsurancePlan"]:
        if "name" not in resource and "identifier" not in resource:
            resource["name"] = "Unknown " + res_type

    # Composition fields
    if res_type == "Composition":
        if "author" not in resource or resource["author"] is None:
            resource["author"] = [{"display": "Unknown Author"}]
        elif not isinstance(resource["author"], list):
            resource["author"] = [resource["author"]]
        for sec in resource.get("section", []):
            if "status" in sec:
                del sec["status"]
            if "text" in sec and isinstance(sec["text"], str):
                sec["text"] = {"status": "generated", "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{sec["text"]}</div>'}
            elif "text" not in sec and "entry" not in sec:
                sec["text"] = {"status": "generated", "div": '<div xmlns="http://www.w3.org/1999/xhtml">No content</div>'}

    # Practitioner qualification
    if res_type == "Practitioner":
        for qual in resource.get("qualification", []):
            if "text" in qual:
                if "code" not in qual:
                    qual["code"] = {"text": qual["text"]}
                del qual["text"]
            if "code" not in qual:
                qual["code"] = {"text": "Unknown Qualification"}

    # Encounter fields
    if res_type == "Encounter":
        if "serviceType" in resource and isinstance(resource["serviceType"], list):
            resource["serviceType"] = resource["serviceType"][0] if resource["serviceType"] else {}
        for loc in resource.get("location", []):
            if "display" in loc:
                loc["location"] = {"display": loc["display"]}
                del loc["display"]
        if "period" in resource and "start" in resource["period"]:
            s = resource["period"]["start"]
            if "T" in s and "Z" not in s and "+" not in s:
                resource["period"]["start"] += "Z"

    # ImagingStudy fields
    if res_type == "ImagingStudy":
        for series in resource.get("series", []):
            if "role" in series:
                del series["role"]
            if "modality" not in series:
                series["modality"] = {"system": "http://dicom.nema.org/resources/ontology/DCM", "code": "UNKNOWN"}
        if "started" in resource and "T" in resource["started"] and "Z" not in resource["started"] and "+" not in resource["started"]:
            resource["started"] += "Z"

    if res_type == "Appointment":
        valid_statuses = ["proposed", "pending", "booked", "arrived", "fulfilled", "cancelled", "noshow", "entered-in-error", "checked-in", "waitlist"]
        if resource.get("status") not in valid_statuses:
            resource["status"] = "fulfilled" if resource.get("status") in ["completed", "finished", "done"] else "booked"

    # DiagnosticReport & Observation dates
    if res_type == "DiagnosticReport":
        for field in ["issued", "effectiveDateTime"]:
            if field in resource and "T" in resource[field] and "Z" not in resource[field] and "+" not in resource[field]:
                resource[field] += "Z"
        if "result" in resource:
            resource["result"] = [r for r in resource["result"] if not r.get("reference", "").startswith("Practitioner/")]

    if res_type == "Observation":
        if "procedure" in resource:
            del resource["procedure"]
        if "effectiveDateTime" in resource and "T" in resource["effectiveDateTime"] and "Z" not in resource["effectiveDateTime"] and "+" not in resource["effectiveDateTime"]:
            resource["effectiveDateTime"] += "Z"

    # Condition category codes
    if res_type == "Condition" and "category" in resource and isinstance(resource["category"], list):
        for cat in resource["category"]:
            if "coding" in cat and isinstance(cat["coding"], list):
                for coding in cat["coding"]:
                    if coding.get("system") == "http://terminology.hl7.org/CodeSystem/condition-category" and coding.get("code") == "encounter-related":
                        coding["code"] = "encounter-diagnosis"


# ── Bundle Reordering ────────────────────────────────────────────────────────

def clean_and_reorder_bundle(bundle):
    """Reorder bundle: Composition FIRST, DocumentReference LAST, remove invalid types."""
    entries = bundle.get("entry", [])
    composition_entry = None
    cleaned_entries = []

    for entry in entries:
        resource = entry.get("resource", {})
        res_type = resource.get("resourceType")

        # Map ABDM/NHCX profile names to standard FHIR R4 types
        if res_type in ["DiagnosticReportRecord", "DischargeSummaryRecord", "WellnessRecord",
                        "HealthDocumentRecord", "PrescriptionRecord", "InsurancePlanBundle"]:
            resource["resourceType"] = "Composition"
            res_type = "Composition"
        elif res_type in ["DiagnosticReportLab", "DiagnosticReportImaging"]:
            resource["resourceType"] = "DiagnosticReport"
            res_type = "DiagnosticReport"
        elif res_type in ["ObservationVitalSigns", "ObservationLifestyle", "ObservationWomenHealth",
                          "ObservationPhysicalActivity", "ObservationGeneralAssessment", "ObservationBodyMeasurement"]:
            resource["resourceType"] = "Observation"
            res_type = "Observation"

        sanitize_fhir_resource(resource)

        if res_type == "Composition":
            composition_entry = entry
        elif res_type == "DocumentBundle":
            continue  # Remove invalid DocumentBundle
        else:
            cleaned_entries.append(entry)

    if composition_entry:
        comp_resource = composition_entry.get("resource", {})
        if "section" not in comp_resource or not comp_resource["section"]:
            comp_resource["section"] = [{"title": "Extracted Data", "text": {"status": "generated", "div": '<div xmlns="http://www.w3.org/1999/xhtml">Auto-generated section</div>'}}]

        all_refs = [{"reference": f"urn:uuid:{e['resource']['id']}"} for e in cleaned_entries if "id" in e.get("resource", {})]
        if all_refs:
            comp_resource["section"][0]["entry"] = all_refs

        bundle["entry"] = [composition_entry] + cleaned_entries
    else:
        bundle["entry"] = cleaned_entries

    return bundle


def embed_pdf_in_document_reference(bundle, pdf_base64):
    """Embed base64-encoded PDF data into DocumentReference resources."""
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        if resource.get("resourceType") == "DocumentReference":
            if "content" not in resource or not resource["content"]:
                resource["content"] = [{"attachment": {"contentType": "application/pdf", "data": pdf_base64}}]
            else:
                attachment = resource["content"][0].setdefault("attachment", {})
                attachment["contentType"] = "application/pdf"
                attachment["data"] = pdf_base64
    return bundle
