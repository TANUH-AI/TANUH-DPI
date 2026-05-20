"""
scripts/test_nhcx_bundles.py — Schema-only golden tests for all 6 NHCX bundle types.

No real PDF required: validates structural contracts, profile constants,
rulebook path resolution, and assemble_nhcx_collection_bundle behaviour.

Run:
    python3 -m pytest scripts/test_nhcx_bundles.py -v
"""
import sys
import os
import uuid
import json
import types

# ── Path setup ────────────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

import pytest

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_bundle(clinical_artifact: str, extra_entries: list = None) -> dict:
    """Build a minimal synthetic bundle as if returned by the LangGraph workflow."""
    from pdf2nhcx.utils.nhcx_profiles import get_profile
    profile = get_profile(clinical_artifact)
    primary_id = str(uuid.uuid4())
    entries = [
        {
            "fullUrl": f"urn:uuid:{primary_id}",
            "resource": {
                "resourceType": profile.primary_resource,
                "id": primary_id,
            }
        }
    ]
    if extra_entries:
        entries.extend(extra_entries)
    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "meta": {"profile": [profile.profile_url]},
        "entry": entries,
    }


# ── nhcx_profiles tests ───────────────────────────────────────────────────────

class TestNhcxProfiles:
    """Tests for nhcx_profiles.py — the single source of truth."""

    def test_all_six_bundle_types_defined(self):
        from pdf2nhcx.utils.nhcx_profiles import NHCX_BUNDLE_TYPES
        expected = {
            "InsurancePlanBundle", "ClaimBundle", "ClaimResponseBundle",
            "CoverageEligibilityRequestBundle", "CoverageEligibilityResponseBundle",
            "TaskBundle",
        }
        assert expected == set(NHCX_BUNDLE_TYPES)

    @pytest.mark.parametrize("bundle_type,primary", [
        ("InsurancePlanBundle", "InsurancePlan"),
        ("ClaimBundle", "Claim"),
        ("ClaimResponseBundle", "ClaimResponse"),
        ("CoverageEligibilityRequestBundle", "CoverageEligibilityRequest"),
        ("CoverageEligibilityResponseBundle", "CoverageEligibilityResponse"),
        ("TaskBundle", "Task"),
    ])
    def test_primary_resource_correct(self, bundle_type, primary):
        from pdf2nhcx.utils.nhcx_profiles import get_profile
        assert get_profile(bundle_type).primary_resource == primary

    @pytest.mark.parametrize("bundle_type", [
        "InsurancePlanBundle", "ClaimBundle", "ClaimResponseBundle",
        "CoverageEligibilityRequestBundle", "CoverageEligibilityResponseBundle",
        "TaskBundle",
    ])
    def test_profile_url_contains_nrces(self, bundle_type):
        from pdf2nhcx.utils.nhcx_profiles import get_profile
        url = get_profile(bundle_type).profile_url
        assert "nrces.in/ndhm/fhir/r4/StructureDefinition" in url, \
            f"Expected NRCES URL, got: {url}"

    def test_get_must_resources_insurance_plan(self):
        from pdf2nhcx.utils.nhcx_profiles import get_must_resources
        musts = get_must_resources("InsurancePlanBundle")
        assert "InsurancePlan" in musts
        assert "Organization" in musts
        assert "DocumentReference" in musts

    def test_get_must_resources_claim(self):
        from pdf2nhcx.utils.nhcx_profiles import get_must_resources
        musts = get_must_resources("ClaimBundle")
        assert "Claim" in musts
        assert "Patient" in musts
        assert "DocumentReference" in musts

    def test_get_must_resources_unknown_fallback(self):
        from pdf2nhcx.utils.nhcx_profiles import get_must_resources
        musts = get_must_resources("SomeUnknownBundle")
        assert "SomeUnknownBundle" in musts
        assert "Organization" in musts

    def test_get_profile_raises_on_unknown(self):
        from pdf2nhcx.utils.nhcx_profiles import get_profile
        with pytest.raises(KeyError):
            get_profile("FakeBundle")

    @pytest.mark.parametrize("bundle_type", [
        "InsurancePlanBundle", "ClaimBundle", "ClaimResponseBundle",
        "CoverageEligibilityRequestBundle", "CoverageEligibilityResponseBundle",
        "TaskBundle",
    ])
    def test_rulebook_filename_pattern(self, bundle_type):
        from pdf2nhcx.utils.nhcx_profiles import get_profile
        fname = get_profile(bundle_type).rulebook_filename
        assert fname.startswith("StructureDefinition-")
        assert fname.endswith("_updated.json")


# ── Rulebook path resolution tests ───────────────────────────────────────────

class TestRulebookPaths:
    """Verifies that all bundle-type rulebook files exist on disk (from module path)."""

    @pytest.mark.parametrize("bundle_type", [
        "InsurancePlanBundle", "ClaimBundle", "ClaimResponseBundle",
        "CoverageEligibilityRequestBundle", "CoverageEligibilityResponseBundle",
        "TaskBundle",
    ])
    def test_rulebook_file_exists(self, bundle_type):
        from pdf2nhcx.utils.nhcx_profiles import get_profile
        profile = get_profile(bundle_type)
        # Anchor to llm_requirements.py location (mirrors production path logic)
        llm_req = os.path.join(_REPO_ROOT, "pdf2nhcx", "utils", "llm_requirements.py")
        rb_dir = os.path.abspath(
            os.path.join(os.path.dirname(llm_req), "..", "rulebooks_updated")
        )
        full_path = os.path.join(rb_dir, profile.rulebook_filename)
        assert os.path.exists(full_path), \
            f"Rulebook file not found: {full_path}"


# ── assemble_nhcx_collection_bundle tests ────────────────────────────────────

class TestAssembleNhcxCollectionBundle:
    """Tests for the NHCX-only bundle assembler."""

    def _get_assembler(self):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        return assemble_nhcx_collection_bundle

    def test_bundle_type_is_collection(self):
        assemble = self._get_assembler()
        bundle = _make_bundle("InsurancePlanBundle")
        result = assemble(bundle, "InsurancePlanBundle")
        assert result["type"] == "collection"

    def test_bundle_resource_type_is_bundle(self):
        assemble = self._get_assembler()
        bundle = _make_bundle("ClaimBundle")
        result = assemble(bundle, "ClaimBundle")
        assert result["resourceType"] == "Bundle"

    def test_correct_nrces_profile_injected(self):
        assemble = self._get_assembler()
        from pdf2nhcx.utils.nhcx_profiles import get_profile
        for bt in ["InsurancePlanBundle", "ClaimBundle", "TaskBundle"]:
            bundle = _make_bundle(bt)
            result = assemble(bundle, bt)
            expected_url = get_profile(bt).profile_url
            assert expected_url in result["meta"]["profile"], \
                f"Profile URL missing for {bt}"

    def test_no_composition_in_output(self):
        """Composition entries must be stripped — they belong to ABDM, not NHCX."""
        assemble = self._get_assembler()
        comp_id = str(uuid.uuid4())
        bundle = _make_bundle("InsurancePlanBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{comp_id}",
            "resource": {"resourceType": "Composition", "id": comp_id, "status": "final",
                         "type": {}, "date": "2024-01-01", "author": [], "title": "t"}
        }])
        result = assemble(bundle, "InsurancePlanBundle")
        types_in_result = [e["resource"]["resourceType"] for e in result["entry"]]
        assert "Composition" not in types_in_result, "Composition must not appear in NHCX bundle"

    def test_no_document_bundle_in_output(self):
        assemble = self._get_assembler()
        db_id = str(uuid.uuid4())
        bundle = _make_bundle("ClaimBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{db_id}",
            "resource": {"resourceType": "DocumentBundle", "id": db_id}
        }])
        result = assemble(bundle, "ClaimBundle")
        types_in_result = [e["resource"]["resourceType"] for e in result["entry"]]
        assert "DocumentBundle" not in types_in_result

    def test_cross_bundle_contamination_stripped(self):
        """A Claim resource must not appear inside an InsurancePlanBundle."""
        assemble = self._get_assembler()
        claim_id = str(uuid.uuid4())
        bundle = _make_bundle("InsurancePlanBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{claim_id}",
            "resource": {
                "resourceType": "Claim", "id": claim_id,
                "status": "active", "use": "claim", "type": {}, "created": "2024-01-01",
                "insurer": {}, "patient": {}, "priority": {},
            }
        }])
        result = assemble(bundle, "InsurancePlanBundle")
        types_in_result = [e["resource"]["resourceType"] for e in result["entry"]]
        assert "Claim" not in types_in_result, \
            "Claim must not appear inside InsurancePlanBundle"

    def test_full_url_is_urn_uuid(self):
        assemble = self._get_assembler()
        bundle = _make_bundle("TaskBundle")
        result = assemble(bundle, "TaskBundle")
        for entry in result["entry"]:
            assert entry["fullUrl"].startswith("urn:uuid:"), \
                f"fullUrl must be urn:uuid:*, got: {entry['fullUrl']}"

    @pytest.mark.parametrize("abdm_type", [
        "DiagnosticReportRecord", "DischargeSummaryRecord", "WellnessRecord",
        "HealthDocumentRecord", "PrescriptionRecord",
    ])
    def test_abdm_profile_names_stripped(self, abdm_type):
        assemble = self._get_assembler()
        bad_id = str(uuid.uuid4())
        bundle = _make_bundle("ClaimResponseBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{bad_id}",
            "resource": {"resourceType": abdm_type, "id": bad_id}
        }])
        result = assemble(bundle, "ClaimResponseBundle")
        types_in_result = [e["resource"]["resourceType"] for e in result["entry"]]
        assert abdm_type not in types_in_result


# ── document_reference_node tests ────────────────────────────────────────────

class TestDocumentReferenceNode:
    """Tests for the fixed document_reference_node."""

    def _get_node(self):
        from pdf2nhcx.utils.nhcx_assembler import document_reference_node
        return document_reference_node

    def test_no_base64_in_docref(self):
        """Base64 data must live in Binary, not in DocumentReference.content."""
        node = self._get_node()
        dr_id = str(uuid.uuid4())
        bundle = {
            "resourceType": "Bundle", "type": "collection", "id": str(uuid.uuid4()),
            "meta": {"profile": ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/InsurancePlanBundle"]},
            "entry": [{
                "fullUrl": f"urn:uuid:{dr_id}",
                "resource": {"resourceType": "DocumentReference", "id": dr_id, "status": "current"}
            }]
        }
        result = node(bundle, pdf_base64="FAKEBASE64DATA==")
        for entry in result["entry"]:
            res = entry["resource"]
            if res.get("resourceType") == "DocumentReference":
                for content_item in res.get("content", []):
                    att = content_item.get("attachment", {})
                    assert "data" not in att, \
                        "base64 data must not be embedded in DocumentReference"

    def test_binary_created_with_pdf_data(self):
        node = self._get_node()
        dr_id = str(uuid.uuid4())
        bundle = {
            "resourceType": "Bundle", "type": "collection", "id": str(uuid.uuid4()),
            "meta": {"profile": []},
            "entry": [{
                "fullUrl": f"urn:uuid:{dr_id}",
                "resource": {"resourceType": "DocumentReference", "id": dr_id, "status": "current"}
            }]
        }
        result = node(bundle, pdf_base64="FAKEBASE64DATA==")
        binary_entries = [
            e for e in result["entry"]
            if e["resource"].get("resourceType") == "Binary"
        ]
        assert len(binary_entries) == 1
        assert binary_entries[0]["resource"]["data"] == "FAKEBASE64DATA=="
        assert binary_entries[0]["resource"]["contentType"] == "application/pdf"

    def test_docref_links_to_binary_via_url(self):
        node = self._get_node()
        dr_id = str(uuid.uuid4())
        bundle = {
            "resourceType": "Bundle", "type": "collection", "id": str(uuid.uuid4()),
            "meta": {"profile": []},
            "entry": [{
                "fullUrl": f"urn:uuid:{dr_id}",
                "resource": {"resourceType": "DocumentReference", "id": dr_id, "status": "current"}
            }]
        }
        result = node(bundle, pdf_base64="FAKEBASE64DATA==")
        binary_id = next(
            e["resource"]["id"] for e in result["entry"]
            if e["resource"].get("resourceType") == "Binary"
        )
        dr = next(
            e["resource"] for e in result["entry"]
            if e["resource"].get("resourceType") == "DocumentReference"
        )
        att = dr["content"][0]["attachment"]
        assert att["url"] == f"urn:uuid:{binary_id}"

    def test_docref_status_set_to_current(self):
        node = self._get_node()
        dr_id = str(uuid.uuid4())
        bundle = {
            "resourceType": "Bundle", "type": "collection", "id": str(uuid.uuid4()),
            "meta": {"profile": []},
            "entry": [{
                "fullUrl": f"urn:uuid:{dr_id}",
                "resource": {"resourceType": "DocumentReference", "id": dr_id}
            }]
        }
        result = node(bundle, pdf_base64="FAKEBASE64DATA==")
        dr = next(e["resource"] for e in result["entry"]
                  if e["resource"].get("resourceType") == "DocumentReference")
        assert dr["status"] == "current"

    def test_no_pdf_base64_returns_bundle_unchanged(self):
        node = self._get_node()
        bundle = {"resourceType": "Bundle", "type": "collection",
                  "id": str(uuid.uuid4()), "meta": {"profile": []}, "entry": []}
        result = node(bundle, pdf_base64=None)
        assert result is bundle  # same object, nothing added


# ── Regression: InsurancePlanBundle (policy document) ────────────────────────

class TestInsurancePlanBundleRegression:
    """
    Structural regression for insurance policy documents.
    Verifies InsurancePlanBundle contract without a real PDF.
    """

    def test_insurance_plan_bundle_has_no_claim(self):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        claim_id = str(uuid.uuid4())
        bundle = _make_bundle("InsurancePlanBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{claim_id}",
            "resource": {"resourceType": "Claim", "id": claim_id,
                         "status": "active", "use": "claim", "type": {}, "created": "2024-01-01",
                         "insurer": {}, "patient": {}, "priority": {}}
        }])
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        types_present = {e["resource"]["resourceType"] for e in result["entry"]}
        assert "Claim" not in types_present

    def test_insurance_plan_bundle_has_no_coverage_eligibility_request(self):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        cer_id = str(uuid.uuid4())
        bundle = _make_bundle("InsurancePlanBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{cer_id}",
            "resource": {"resourceType": "CoverageEligibilityRequest", "id": cer_id,
                         "status": "active", "purpose": ["benefits"],
                         "patient": {}, "created": "2024-01-01", "insurer": {}}
        }])
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        types_present = {e["resource"]["resourceType"] for e in result["entry"]}
        assert "CoverageEligibilityRequest" not in types_present

    def test_insurance_plan_bundle_has_no_composition(self):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        comp_id = str(uuid.uuid4())
        bundle = _make_bundle("InsurancePlanBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{comp_id}",
            "resource": {"resourceType": "Composition", "id": comp_id,
                         "status": "final", "type": {}, "date": "2024-01-01",
                         "author": [], "title": "t"}
        }])
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        types_present = {e["resource"]["resourceType"] for e in result["entry"]}
        assert "Composition" not in types_present

    def test_insurance_plan_bundle_type_is_collection(self):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        bundle = _make_bundle("InsurancePlanBundle")
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        assert result["type"] == "collection"

    def test_insurance_plan_bundle_profile_url(self):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        bundle = _make_bundle("InsurancePlanBundle")
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        assert any(
            "InsurancePlanBundle" in p
            for p in result["meta"]["profile"]
        )



# ── TestStrictResourceRouting ─────────────────────────────────────────────────

class TestStrictResourceRouting:
    """
    Validates strict per-bundle resource routing rules from nhcx_profiles.py.
    Tests requested by Codex review:
    - Primary resource present for all 6 bundle types
    - InsurancePlanBundle hard-pruning: no Condition, nested Bundle, or workflow resources
    - Nested Bundle flattening with fullUrl preservation and deduplication
    - strip_binary_data removes Binary.data and optionally sets Binary.url
    - ClaimBundle regression: Condition IS still allowed (patient diagnosis)
    - get_forbidden_resources correctness
    - forbidden_resources never overlaps allowed_supporting
    """

    # ── Primary resource presence: all 6 bundle types ──────────────────────────

    @pytest.mark.parametrize("bundle_type,primary", [
        ("InsurancePlanBundle", "InsurancePlan"),
        ("ClaimBundle", "Claim"),
        ("ClaimResponseBundle", "ClaimResponse"),
        ("CoverageEligibilityRequestBundle", "CoverageEligibilityRequest"),
        ("CoverageEligibilityResponseBundle", "CoverageEligibilityResponse"),
        ("TaskBundle", "Task"),
    ])
    def test_primary_resource_present_after_assembly(self, bundle_type, primary):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        bundle = _make_bundle(bundle_type)
        result = assemble_nhcx_collection_bundle(bundle, bundle_type)
        types_present = {e["resource"]["resourceType"] for e in result["entry"]}
        assert primary in types_present, \
            f"Primary resource '{primary}' must be present in {bundle_type}"

    # ── InsurancePlanBundle: no Condition ──────────────────────────────────────

    def test_insurance_plan_bundle_no_condition(self):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        cond_id = str(uuid.uuid4())
        bundle = _make_bundle("InsurancePlanBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{cond_id}",
            "resource": {
                "resourceType": "Condition", "id": cond_id,
                "code": {"text": "Congenital Anomaly"},
                "subject": {"reference": "urn:uuid:fake"},
            }
        }])
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        types_present = {e["resource"]["resourceType"] for e in result["entry"]}
        assert "Condition" not in types_present, \
            "Condition must be stripped from InsurancePlanBundle"

    # ── InsurancePlanBundle: no PractitionerRole ───────────────────────────────

    def test_insurance_plan_bundle_no_practitioner_role(self):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        pr_id = str(uuid.uuid4())
        bundle = _make_bundle("InsurancePlanBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{pr_id}",
            "resource": {"resourceType": "PractitionerRole", "id": pr_id}
        }])
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        types_present = {e["resource"]["resourceType"] for e in result["entry"]}
        assert "PractitionerRole" not in types_present

    # ── InsurancePlanBundle: no Task / eligibility / ClaimResponse ─────────────

    @pytest.mark.parametrize("forbidden_type", [
        "Task", "CoverageEligibilityRequest", "CoverageEligibilityResponse", "ClaimResponse",
    ])
    def test_insurance_plan_bundle_no_workflow_resources(self, forbidden_type):
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        fid = str(uuid.uuid4())
        bundle = _make_bundle("InsurancePlanBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{fid}",
            "resource": {"resourceType": forbidden_type, "id": fid}
        }])
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        types_present = {e["resource"]["resourceType"] for e in result["entry"]}
        assert forbidden_type not in types_present, \
            f"'{forbidden_type}' must be stripped from InsurancePlanBundle"

    # ── Nested Bundle flattening ───────────────────────────────────────────────

    def test_nested_bundle_flattened(self):
        """InsurancePlan inside a nested Bundle must be promoted to top level."""
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        inner_id = str(uuid.uuid4())
        org_id = str(uuid.uuid4())
        nested_bundle_id = str(uuid.uuid4())
        # Build a bundle whose single entry is itself a Bundle
        bundle = {
            "resourceType": "Bundle",
            "id": str(uuid.uuid4()),
            "type": "collection",
            "meta": {"profile": []},
            "entry": [{
                "fullUrl": f"urn:uuid:{nested_bundle_id}",
                "resource": {
                    "resourceType": "Bundle",
                    "id": nested_bundle_id,
                    "type": "collection",
                    "entry": [
                        {
                            "fullUrl": f"urn:uuid:{inner_id}",
                            "resource": {
                                "resourceType": "InsurancePlan",
                                "id": inner_id,
                                "name": "Swasthya Sathi",
                            }
                        },
                        {
                            "fullUrl": f"urn:uuid:{org_id}",
                            "resource": {
                                "resourceType": "Organization",
                                "id": org_id,
                                "name": "West Bengal Government",
                            }
                        }
                    ]
                }
            }]
        }
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        types_present = {e["resource"]["resourceType"] for e in result["entry"]}
        assert "InsurancePlan" in types_present, \
            "InsurancePlan must be promoted from nested Bundle"
        assert "Organization" in types_present, \
            "Organization must be promoted from nested Bundle"
        # The nested Bundle wrapper itself must be gone
        assert "Bundle" not in types_present, \
            "Nested Bundle wrapper must be dropped"

    def test_nested_bundle_fullurl_preserved(self):
        """fullUrls of children extracted from nested Bundle must be urn:uuid:* refs."""
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        inner_id = str(uuid.uuid4())
        nested_bundle_id = str(uuid.uuid4())
        bundle = {
            "resourceType": "Bundle", "id": str(uuid.uuid4()),
            "type": "collection", "meta": {"profile": []},
            "entry": [{
                "fullUrl": f"urn:uuid:{nested_bundle_id}",
                "resource": {
                    "resourceType": "Bundle", "id": nested_bundle_id, "type": "collection",
                    "entry": [{
                        "fullUrl": f"urn:uuid:{inner_id}",
                        "resource": {"resourceType": "InsurancePlan", "id": inner_id, "name": "X"}
                    }]
                }
            }]
        }
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        for entry in result["entry"]:
            assert entry["fullUrl"].startswith("urn:uuid:"), \
                f"All fullUrls must be urn:uuid:*, got: {entry['fullUrl']}"

    def test_nested_bundle_deduplication(self):
        """If a resource appears both top-level and inside a nested Bundle, keep only one."""
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        dup_id = str(uuid.uuid4())
        nested_bundle_id = str(uuid.uuid4())
        bundle = {
            "resourceType": "Bundle", "id": str(uuid.uuid4()),
            "type": "collection", "meta": {"profile": []},
            "entry": [
                # Top-level InsurancePlan
                {
                    "fullUrl": f"urn:uuid:{dup_id}",
                    "resource": {"resourceType": "InsurancePlan", "id": dup_id, "name": "Plan A"}
                },
                # Nested Bundle containing the SAME InsurancePlan id
                {
                    "fullUrl": f"urn:uuid:{nested_bundle_id}",
                    "resource": {
                        "resourceType": "Bundle", "id": nested_bundle_id, "type": "collection",
                        "entry": [{
                            "fullUrl": f"urn:uuid:{dup_id}",
                            "resource": {"resourceType": "InsurancePlan", "id": dup_id, "name": "Plan A"}
                        }]
                    }
                }
            ]
        }
        result = assemble_nhcx_collection_bundle(bundle, "InsurancePlanBundle")
        insurance_plans = [
            e for e in result["entry"]
            if e["resource"]["resourceType"] == "InsurancePlan"
        ]
        assert len(insurance_plans) == 1, "Duplicate resource IDs must be deduplicated"

    # ── strip_binary_data ──────────────────────────────────────────────────────

    def test_strip_binary_data_removes_data(self):
        from pdf2nhcx.utils.nhcx_assembler import strip_binary_data
        bin_id = str(uuid.uuid4())
        bundle = {
            "resourceType": "Bundle", "type": "collection",
            "entry": [{
                "fullUrl": f"urn:uuid:{bin_id}",
                "resource": {
                    "resourceType": "Binary", "id": bin_id,
                    "contentType": "application/pdf",
                    "data": "AAAAAAAAAAAABBBBCCCC==",
                }
            }]
        }
        result = strip_binary_data(bundle)
        binary = next(e["resource"] for e in result["entry"]
                      if e["resource"]["resourceType"] == "Binary")
        assert "data" not in binary, "Binary.data must be removed by strip_binary_data"
        assert binary["contentType"] == "application/pdf", "contentType must be preserved"

    def test_strip_binary_data_sets_gcs_url_on_docref(self):
        """GCS URI must go to DocumentReference.content[].attachment.url, not Binary.url."""
        from pdf2nhcx.utils.nhcx_assembler import strip_binary_data
        bin_id = str(uuid.uuid4())
        dr_id = str(uuid.uuid4())
        bundle = {
            "resourceType": "Bundle", "type": "collection",
            "entry": [
                {
                    "fullUrl": f"urn:uuid:{bin_id}",
                    "resource": {
                        "resourceType": "Binary", "id": bin_id,
                        "contentType": "application/pdf",
                        "data": "AAAAAAAAAAAABBBBCCCC==",
                    }
                },
                {
                    "fullUrl": f"urn:uuid:{dr_id}",
                    "resource": {
                        "resourceType": "DocumentReference", "id": dr_id,
                        "status": "current",
                        "content": [{"attachment": {"contentType": "application/pdf", "url": f"urn:uuid:{bin_id}"}}],
                    }
                },
            ]
        }
        gcs_uri = "gs://nhcx-fhir-bucket/pdf_uploads/nhcx/swasthya_sathi.pdf"
        result = strip_binary_data(bundle, gcs_pdf_uri=gcs_uri)
        binary = next(e["resource"] for e in result["entry"]
                      if e["resource"]["resourceType"] == "Binary")
        assert "data" not in binary
        assert "url" not in binary, "Binary must NOT have url; URI goes on DocumentReference"
        dr = next(e["resource"] for e in result["entry"]
                  if e["resource"]["resourceType"] == "DocumentReference")
        assert dr["content"][0]["attachment"]["url"] == gcs_uri, \
            "DocumentReference.content.attachment.url must be the GCS URI"

    def test_strip_binary_data_no_binary_no_error(self):
        from pdf2nhcx.utils.nhcx_assembler import strip_binary_data
        bundle = {"resourceType": "Bundle", "type": "collection", "entry": []}
        result = strip_binary_data(bundle, gcs_pdf_uri="gs://bucket/file.pdf")
        assert result["entry"] == []

    # ── ClaimBundle regression: Condition IS allowed ───────────────────────────

    def test_claim_bundle_allows_condition(self):
        """Condition must NOT be stripped from ClaimBundle (valid patient diagnosis)."""
        from pdf2nhcx.utils.nhcx_assembler import assemble_nhcx_collection_bundle
        cond_id = str(uuid.uuid4())
        bundle = _make_bundle("ClaimBundle", extra_entries=[{
            "fullUrl": f"urn:uuid:{cond_id}",
            "resource": {
                "resourceType": "Condition", "id": cond_id,
                "code": {"coding": [{"system": "http://snomed.info/sct", "code": "38341003"}]},
                "subject": {"reference": "urn:uuid:patient-1"},
            }
        }])
        result = assemble_nhcx_collection_bundle(bundle, "ClaimBundle")
        types_present = {e["resource"]["resourceType"] for e in result["entry"]}
        assert "Condition" in types_present, \
            "Condition must remain in ClaimBundle (patient diagnosis)"

    # ── get_forbidden_resources correctness ───────────────────────────────────

    @pytest.mark.parametrize("bundle_type,must_be_forbidden", [
        ("InsurancePlanBundle", {"Condition", "Claim", "Task", "CoverageEligibilityRequest"}),
        ("ClaimBundle", {"InsurancePlan", "Task"}),
        ("ClaimResponseBundle", {"Condition", "InsurancePlan", "Task"}),
        ("CoverageEligibilityRequestBundle", {"Claim", "ClaimResponse", "Task"}),
        ("CoverageEligibilityResponseBundle", {"Claim", "ClaimResponse", "Task"}),
        ("TaskBundle", {"InsurancePlan", "Condition"}),
    ])
    def test_get_forbidden_resources_correct(self, bundle_type, must_be_forbidden):
        from pdf2nhcx.utils.nhcx_profiles import get_forbidden_resources
        forbidden = get_forbidden_resources(bundle_type)
        for resource_type in must_be_forbidden:
            assert resource_type in forbidden, \
                f"'{resource_type}' must be in forbidden_resources for {bundle_type}"

    # ── forbidden_resources never overlaps allowed_supporting ──────────────────

    @pytest.mark.parametrize("bundle_type", [
        "InsurancePlanBundle", "ClaimBundle", "ClaimResponseBundle",
        "CoverageEligibilityRequestBundle", "CoverageEligibilityResponseBundle",
        "TaskBundle",
    ])
    def test_forbidden_never_overlaps_allowed_supporting(self, bundle_type):
        from pdf2nhcx.utils.nhcx_profiles import get_profile, get_forbidden_resources
        profile = get_profile(bundle_type)
        forbidden = get_forbidden_resources(bundle_type)
        allowed = set(profile.allowed_supporting)
        overlap = forbidden & allowed
        assert not overlap, \
            f"{bundle_type}: forbidden_resources and allowed_supporting overlap: {overlap}"

    # ── InsurancePlanBundle condition from nhcx_profiles ─────────────────────

    def test_insurance_plan_bundle_condition_not_in_must_or_allowed(self):
        from pdf2nhcx.utils.nhcx_profiles import get_profile
        profile = get_profile("InsurancePlanBundle")
        all_positive = set(profile.must_resources) | set(profile.allowed_supporting)
        assert "Condition" not in all_positive, \
            "Condition must not be in InsurancePlanBundle must_resources or allowed_supporting"


# ── TestSanitizerFixes ─────────────────────────────────────────────────────────

class TestSanitizerFixes:
    """
    Tests for specific sanitizer guards in sanitize_fhir_resource:
    - display: 'collection' removal
    - DocumentReference.type proper CodeableConcept
    - InsurancePlan.coverage.benefit.claimable deletion
    - InsurancePlan.coverage.benefit.requirement array-to-string
    - InsurancePlan.coverage.exclusion -> NRCeS Claim-Exclusion extension
    """

    def _sanitize(self, resource):
        import sys
        from unittest.mock import MagicMock
        # Stub out ALL heavy runtime dependencies that llm_requirements.py imports
        # at module level but sanitize_fhir_resource doesn't actually use.
        _modules_to_stub = [
            'langgraph', 'langgraph.graph',
            'langchain_core', 'langchain_core.tools', 'langchain_core.messages',
            'langchain_google_vertexai',
            'langchain_ollama',
        ]
        _stubs = {}
        for mod in _modules_to_stub:
            if mod not in sys.modules:
                _stubs[mod] = sys.modules[mod] = MagicMock()
        try:
            from pdf2nhcx.utils.llm_requirements import sanitize_fhir_resource
            sanitize_fhir_resource(resource)
        finally:
            for mod in _stubs:
                sys.modules.pop(mod, None)
        return resource

    # ── display: "collection" removal ────────────────────────────────────

    def test_display_collection_removed_from_codeable_concept(self):
        res = self._sanitize({
            "resourceType": "Organization",
            "id": str(uuid.uuid4()),
            "name": "Test Org",
            "type": [{"coding": [{"code": "collection", "display": "collection",
                                  "system": "http://terminology.hl7.org/CodeSystem/organization-type"}]}],
        })
        coding = res["type"][0]["coding"][0]
        assert coding.get("code") != "collection"
        assert coding.get("display") != "collection"

    def test_display_collection_removed_from_bare_display(self):
        res = self._sanitize({
            "resourceType": "InsurancePlan",
            "id": str(uuid.uuid4()),
            "name": "Test Plan",
            "ownedBy": {"reference": "urn:uuid:abc", "display": "collection"},
        })
        assert res["ownedBy"].get("display") is None, \
            "Bare display='collection' must be removed from references"

    def test_display_collection_removed_from_text(self):
        res = self._sanitize({
            "resourceType": "Coverage",
            "id": str(uuid.uuid4()),
            "status": "active",
            "beneficiary": {"display": "Patient"},
            "payor": [{"display": "Org"}],
            "type": {"text": "Collection"},
        })
        assert res["type"].get("text") is None, \
            "text='Collection' must be stripped from CodeableConcept"

    # ── DocumentReference.type ───────────────────────────────────────

    def test_docref_type_gets_snomed_coding_when_missing(self):
        res = self._sanitize({
            "resourceType": "DocumentReference",
            "id": str(uuid.uuid4()),
            "status": "current",
        })
        assert isinstance(res["type"], dict)
        assert "coding" in res["type"]
        assert res["type"]["coding"][0]["system"] == "http://snomed.info/sct"
        assert res["type"]["coding"][0]["code"] == "419891008"

    def test_docref_type_gets_coding_added_when_only_text(self):
        res = self._sanitize({
            "resourceType": "DocumentReference",
            "id": str(uuid.uuid4()),
            "status": "current",
            "type": {"text": "Policy Document"},
        })
        assert "coding" in res["type"], "coding must be added when only text exists"
        assert res["type"]["text"] == "Policy Document", "original text preserved"

    def test_docref_type_list_flattened(self):
        res = self._sanitize({
            "resourceType": "DocumentReference",
            "id": str(uuid.uuid4()),
            "status": "current",
            "type": [{"text": "doc1"}, {"text": "doc2"}],
        })
        assert isinstance(res["type"], dict), "type must be a single CodeableConcept, not array"

    # ── InsurancePlan.coverage.benefit.claimable ───────────────────────

    def test_benefit_claimable_deleted(self):
        res = self._sanitize({
            "resourceType": "InsurancePlan",
            "id": str(uuid.uuid4()),
            "name": "Test Plan",
            "coverage": [{
                "type": {"text": "Medical"},
                "benefit": [{
                    "type": {"text": "Hospitalization"},
                    "claimable": True,
                    "requirement": "Must be admitted",
                }]
            }]
        })
        for cov in res["coverage"]:
            for ben in cov["benefit"]:
                assert "claimable" not in ben, \
                    "claimable does not exist in FHIR R4 and must be deleted"

    # ── InsurancePlan.coverage.benefit.requirement: array-to-string ────────

    def test_benefit_requirement_array_of_objects_to_string(self):
        res = self._sanitize({
            "resourceType": "InsurancePlan",
            "id": str(uuid.uuid4()),
            "name": "Test Plan",
            "coverage": [{
                "type": {"text": "Medical"},
                "benefit": [{
                    "type": {"text": "Hospitalization"},
                    "requirement": [
                        {"text": "Includes pre-existing diseases"},
                        {"text": "Subject to waiting period"},
                    ]
                }]
            }]
        })
        req = res["coverage"][0]["benefit"][0]["requirement"]
        assert isinstance(req, str), f"requirement must be a string, got {type(req)}"
        assert "Includes pre-existing diseases" in req
        assert "Subject to waiting period" in req

    def test_benefit_requirement_single_object_to_string(self):
        res = self._sanitize({
            "resourceType": "InsurancePlan",
            "id": str(uuid.uuid4()),
            "name": "Test Plan",
            "coverage": [{
                "type": {"text": "Medical"},
                "benefit": [{
                    "type": {"text": "Hospitalization"},
                    "requirement": {"text": "Must be admitted"},
                }]
            }]
        })
        req = res["coverage"][0]["benefit"][0]["requirement"]
        assert isinstance(req, str), f"requirement must be a string, got {type(req)}"
        assert req == "Must be admitted"

    def test_benefit_requirement_string_unchanged(self):
        res = self._sanitize({
            "resourceType": "InsurancePlan",
            "id": str(uuid.uuid4()),
            "name": "Test Plan",
            "coverage": [{
                "type": {"text": "Medical"},
                "benefit": [{
                    "type": {"text": "Hospitalization"},
                    "requirement": "Already a string",
                }]
            }]
        })
        assert res["coverage"][0]["benefit"][0]["requirement"] == "Already a string"

    # ── InsurancePlan.coverage.exclusion -> NRCeS Claim-Exclusion extension ──

    def test_coverage_exclusion_moved_to_extension(self):
        res = self._sanitize({
            "resourceType": "InsurancePlan",
            "id": str(uuid.uuid4()),
            "name": "Swasthya Sathi",
            "coverage": [{
                "type": {"text": "Medical"},
                "benefit": [{"type": {"text": "Hospitalization"}}],
                "exclusion": [
                    {"text": "Outpatient (OPD) Care"},
                    {"text": "Cosmetic Surgery"},
                ]
            }]
        })
        # exclusion must be gone from coverage
        for cov in res["coverage"]:
            assert "exclusion" not in cov, "coverage.exclusion must be removed"
        # Must appear as NRCeS Claim-Exclusion extensions on the resource
        exts = [e for e in res.get("extension", [])
                if e.get("url") == "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Claim-Exclusion"]
        assert len(exts) == 2, f"Expected 2 Claim-Exclusion extensions, got {len(exts)}"
        # Each extension should have statement + item sub-extensions
        for ext in exts:
            sub_urls = {se["url"] for se in ext.get("extension", [])}
            assert "statement" in sub_urls, "Claim-Exclusion must have 'statement' sub-extension"
            assert "item" in sub_urls, "Claim-Exclusion must have 'item' sub-extension"

    def test_top_level_exclusion_moved_to_extension(self):
        res = self._sanitize({
            "resourceType": "InsurancePlan",
            "id": str(uuid.uuid4()),
            "name": "Test Plan",
            "exclusion": [{"text": "Pre-existing conditions not covered"}],
        })
        assert "exclusion" not in res, "top-level exclusion must be removed"
        exts = [e for e in res.get("extension", [])
                if e.get("url") == "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Claim-Exclusion"]
        assert len(exts) == 1

    def test_string_exclusion_moved_to_extension(self):
        res = self._sanitize({
            "resourceType": "InsurancePlan",
            "id": str(uuid.uuid4()),
            "name": "Test Plan",
            "exclusion": ["Dental care is not covered"],
        })
        assert "exclusion" not in res
        exts = [e for e in res.get("extension", [])
                if e.get("url") == "https://nrces.in/ndhm/fhir/r4/StructureDefinition/Claim-Exclusion"]
        assert len(exts) == 1
        statement = next(
            se["valueString"] for se in exts[0]["extension"] if se["url"] == "statement"
        )
        assert statement == "Dental care is not covered"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
