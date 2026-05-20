"""
pdf2nhcx/utils/nhcx_profiles.py — Single source of truth for all NHCX bundle-type definitions.

Both ocr_engine.py and llm_requirements.py import from here to avoid duplication.

Resource tiers per bundle
--------------------------
primary_resource   : the single required anchor entry (Claim, Task, InsurancePlan, …)
must_resources     : always extracted, regardless of LLM selection (bundle anchor + minimal org set)
allowed_supporting : LLM may optionally include these based on document content
forbidden_resources: explicitly rejected by the assembler even if the LLM emits them

Key policy decisions
---------------------
- Condition is NOT in InsurancePlanBundle — policy terms (Congenital Anomaly, Pre-existing
  Disease, Waiting Period) belong inside InsurancePlan.coverage.benefit / .exclusion.
- Condition IS allowed in ClaimBundle (patient diagnosis supporting a claim).
- must_resources is kept small: only the anchor resource, Organization, and DocumentReference.
  Everything else (Coverage, Patient, Practitioner, Procedure, …) is optional/recommended.
- forbidden_resources is used by the assembler to hard-drop resources regardless of what
  the LLM emitted.
"""
from dataclasses import dataclass
from typing import Dict, FrozenSet, List


@dataclass(frozen=True)
class NHCXBundleProfile:
    bundle_type: str           # logical name, e.g. "ClaimBundle"
    profile_url: str           # NRCES StructureDefinition URL
    primary_resource: str      # required anchor entry, e.g. "Claim"
    must_resources: tuple      # always extracted (small, high-confidence set)
    allowed_supporting: tuple  # LLM may optionally include these
    forbidden_resources: tuple # hard-dropped by assembler even if LLM emits them
    rulebook_filename: str     # filename inside rulebooks_updated/


# ── Canonical profile definitions ──────────────────────────────────────────────

_PROFILES: List[NHCXBundleProfile] = [

    NHCXBundleProfile(
        bundle_type="InsurancePlanBundle",
        profile_url="https://nrces.in/ndhm/fhir/r4/StructureDefinition/InsurancePlanBundle",
        primary_resource="InsurancePlan",
        # Minimal required set — do NOT force Condition, Coverage, Practitioner, etc.
        must_resources=(
            "InsurancePlanBundle", "InsurancePlan", "Organization", "DocumentReference",
        ),
        # Only resources that make sense in a policy document
        allowed_supporting=(
            "Binary",
        ),
        # Hard-forbidden: policy docs are not patient records and not workflow resources
        forbidden_resources=(
            "Condition", "Claim", "ClaimResponse",
            "CoverageEligibilityRequest", "CoverageEligibilityResponse",
            "Task", "PractitionerRole", "Practitioner", "Patient",
            "Coverage", "Procedure", "PaymentNotice", "PaymentReconciliation",
            "Communication", "CommunicationRequest",
        ),
        rulebook_filename="StructureDefinition-InsurancePlanBundle_updated.json",
    ),

    NHCXBundleProfile(
        bundle_type="ClaimBundle",
        profile_url="https://nrces.in/ndhm/fhir/r4/StructureDefinition/ClaimBundle",
        primary_resource="Claim",
        must_resources=(
            "ClaimBundle", "Claim", "Organization", "Patient", "DocumentReference",
        ),
        # Condition IS allowed here — represents patient diagnosis supporting the claim
        allowed_supporting=(
            "Coverage", "Condition", "Procedure",
            "Practitioner", "PractitionerRole", "PaymentNotice", "Binary",
        ),
        forbidden_resources=(
            "InsurancePlan",
            "CoverageEligibilityResponse",
            "Task",
            "Communication", "CommunicationRequest",
            "PaymentReconciliation",
        ),
        rulebook_filename="StructureDefinition-ClaimBundle_updated.json",
    ),

    NHCXBundleProfile(
        bundle_type="ClaimResponseBundle",
        profile_url="https://nrces.in/ndhm/fhir/r4/StructureDefinition/ClaimResponseBundle",
        primary_resource="ClaimResponse",
        must_resources=(
            "ClaimResponseBundle", "ClaimResponse", "Organization", "Patient", "DocumentReference",
        ),
        # Condition and Procedure removed — adjudication responses don't describe patient conditions
        allowed_supporting=(
            "Coverage", "Claim",
            "PaymentNotice", "PaymentReconciliation",
            "Communication", "Binary",
        ),
        forbidden_resources=(
            "InsurancePlan",
            "CoverageEligibilityRequest",
            "Task",
            "Condition", "Procedure",
            "CommunicationRequest",
        ),
        rulebook_filename="StructureDefinition-ClaimResponseBundle_updated.json",
    ),

    NHCXBundleProfile(
        bundle_type="CoverageEligibilityRequestBundle",
        profile_url="https://nrces.in/ndhm/fhir/r4/StructureDefinition/CoverageEligibilityRequestBundle",
        primary_resource="CoverageEligibilityRequest",
        must_resources=(
            "CoverageEligibilityRequestBundle", "CoverageEligibilityRequest",
            "Organization", "Patient", "DocumentReference",
        ),
        allowed_supporting=(
            "Coverage", "InsurancePlan",
            "Practitioner", "PractitionerRole", "Binary",
        ),
        forbidden_resources=(
            "Claim", "ClaimResponse",
            "CoverageEligibilityResponse",
            "Task",
            "Condition", "Procedure",
            "PaymentNotice", "PaymentReconciliation",
            "Communication", "CommunicationRequest",
        ),
        rulebook_filename="StructureDefinition-CoverageEligibilityRequestBundle_updated.json",
    ),

    NHCXBundleProfile(
        bundle_type="CoverageEligibilityResponseBundle",
        profile_url="https://nrces.in/ndhm/fhir/r4/StructureDefinition/CoverageEligibilityResponseBundle",
        primary_resource="CoverageEligibilityResponse",
        must_resources=(
            "CoverageEligibilityResponseBundle", "CoverageEligibilityResponse",
            "Organization", "Patient", "DocumentReference",
        ),
        allowed_supporting=(
            "Coverage", "InsurancePlan",
            "CoverageEligibilityRequest",
            "Practitioner", "Binary",
        ),
        forbidden_resources=(
            "Claim", "ClaimResponse",
            "Task",
            "Condition", "Procedure",
            "PaymentNotice", "PaymentReconciliation",
            "Communication", "CommunicationRequest",
        ),
        rulebook_filename="StructureDefinition-CoverageEligibilityResponseBundle_updated.json",
    ),

    NHCXBundleProfile(
        bundle_type="TaskBundle",
        profile_url="https://nrces.in/ndhm/fhir/r4/StructureDefinition/TaskBundle",
        primary_resource="Task",
        must_resources=(
            "TaskBundle", "Task", "Organization", "Patient", "DocumentReference",
        ),
        # Task bundles may reference Claim/ClaimResponse/eligibility as Task.focus targets
        allowed_supporting=(
            "Claim", "ClaimResponse",
            "CoverageEligibilityRequest", "CoverageEligibilityResponse",
            "Communication", "CommunicationRequest",
            "PaymentNotice", "PaymentReconciliation",
            "Binary",
        ),
        # TaskBundle has no hard-forbidden NHCX resources (it coordinates them)
        forbidden_resources=(
            "InsurancePlan",
            "Condition", "Procedure",
        ),
        rulebook_filename="StructureDefinition-TaskBundle_updated.json",
    ),
]

# ── Lookup helpers ──────────────────────────────────────────────────────────────

# Keyed by bundle_type string for O(1) access
PROFILES_BY_TYPE: Dict[str, NHCXBundleProfile] = {p.bundle_type: p for p in _PROFILES}

# Set of all known NHCX bundle type names
NHCX_BUNDLE_TYPES: FrozenSet[str] = frozenset(PROFILES_BY_TYPE.keys())

# Convenience maps
BUNDLE_PROFILES: Dict[str, str]       = {p.bundle_type: p.profile_url        for p in _PROFILES}
BUNDLE_PRIMARY_RESOURCE: Dict[str, str] = {p.bundle_type: p.primary_resource  for p in _PROFILES}
BUNDLE_MUST_RESOURCES: Dict[str, List[str]] = {p.bundle_type: list(p.must_resources) for p in _PROFILES}


def get_profile(bundle_type: str) -> NHCXBundleProfile:
    """Return the NHCXBundleProfile for a given bundle_type, or raise KeyError."""
    if bundle_type not in PROFILES_BY_TYPE:
        raise KeyError(
            f"Unknown NHCX bundle type: {bundle_type!r}. "
            f"Valid types: {sorted(NHCX_BUNDLE_TYPES)}"
        )
    return PROFILES_BY_TYPE[bundle_type]


def get_must_resources(bundle_type: str) -> List[str]:
    """Return the mandatory resource list for a given NHCX bundle type."""
    profile = PROFILES_BY_TYPE.get(bundle_type)
    if profile:
        return list(profile.must_resources)
    return [bundle_type, "Organization", "DocumentReference"]


def get_allowed_supporting(bundle_type: str) -> List[str]:
    """Return the list of optional resources the LLM may include."""
    profile = PROFILES_BY_TYPE.get(bundle_type)
    return list(profile.allowed_supporting) if profile else []


def get_forbidden_resources(bundle_type: str) -> FrozenSet[str]:
    """Return the set of resources that must never appear in this bundle type."""
    profile = PROFILES_BY_TYPE.get(bundle_type)
    return frozenset(profile.forbidden_resources) if profile else frozenset()
