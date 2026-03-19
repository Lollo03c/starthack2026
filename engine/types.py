"""
All shared dataclasses for the ChainIQ supplier ranking pipeline.
Every other module imports from here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


# ---------------------------------------------------------------------------
# LLM decomposition outputs (from Phase 0)
# ---------------------------------------------------------------------------

@dataclass
class StructuredCheck:
    check: str          # known check type (e.g. "has_capability")
    value: Any
    operator: str = "eq"


@dataclass
class UnknownCheck:
    check: str          # short description
    description: str    # full verifiable description
    field_path: str = ""
    operator: str = ""
    value: Any = None


@dataclass
class SubjectiveCriterion:
    criterion: str
    importance: str = "nice_to_have"   # "must_have" | "nice_to_have"


@dataclass
class DecompositionResult:
    success: bool
    structured_checks: list[StructuredCheck] = field(default_factory=list)
    unknown_checks: list[UnknownCheck] = field(default_factory=list)
    subjective_criteria: list[SubjectiveCriterion] = field(default_factory=list)
    quantity_in_text: float | None = None
    detected_language: str = "en"


@dataclass
class FitScoreResult:
    score: float        # 0.0–1.0
    rationale: str
    success: bool


# ---------------------------------------------------------------------------
# Data rows (loaded from CSV / JSON)
# ---------------------------------------------------------------------------

@dataclass
class SupplierRow:
    supplier_id: str
    supplier_name: str
    category_l1: str
    category_l2: str
    country_hq: str
    service_regions: frozenset[str]    # parsed from semicolon-separated string
    currency: str
    pricing_model: str
    quality_score: int
    risk_score: int
    esg_score: int
    preferred_supplier: bool
    is_restricted: bool                # hint only — use policies.json for authoritative check
    restriction_reason: str
    contract_status: str
    data_residency_supported: bool
    capacity_per_month: int
    notes: str


@dataclass
class PricingTier:
    pricing_id: str
    supplier_id: str
    category_l1: str
    category_l2: str
    region: str
    currency: str
    pricing_model: str
    min_quantity: float
    max_quantity: float
    unit_price: float
    moq: float
    standard_lead_time_days: int
    expedited_lead_time_days: int
    expedited_unit_price: float
    valid_from: date
    valid_to: date
    notes: str

    def total_price(self, quantity: float) -> float:
        return self.unit_price * quantity

    def expedited_total_price(self, quantity: float) -> float:
        return self.expedited_unit_price * quantity


@dataclass
class ApprovalThreshold:
    rule_id: str
    currency: str
    min_amount: float
    max_amount: float          # float('inf') for open-ended
    quotes_required: int
    approvers: list[str]
    deviation_approval: str    # role name
    notes: str = ""


@dataclass
class CategoryRow:
    category_l1: str
    category_l2: str
    description: str
    typical_unit: str
    pricing_model: str


@dataclass
class AwardRow:
    award_id: str
    request_id: str
    awarded_supplier_id: str
    supplier_name: str
    category_l1: str
    category_l2: str
    award_rank: int
    award_date: str
    awarded: bool
    total_award_value: float
    currency: str
    decision_rationale: str
    savings_pct: float
    lead_time_days: int
    risk_score_at_award: int
    notes: str


# ---------------------------------------------------------------------------
# Escalation (collected during pipeline, IDs assigned in output_builder)
# ---------------------------------------------------------------------------

@dataclass
class Escalation:
    rule_id: str            # e.g. "ER-002"
    trigger: str
    escalate_to: str
    blocking: bool
    escalation_id: str = ""  # assigned by output_builder


# ---------------------------------------------------------------------------
# Phase 0 output
# ---------------------------------------------------------------------------

@dataclass
class RequestContext:
    # Raw request fields
    request_id: str
    created_at: str
    request_channel: str
    request_language: str
    business_unit: str
    country: str
    site: str
    requester_id: str
    requester_role: str
    submitted_for_id: str
    category_l1: str
    category_l2: str
    title: str
    request_text: str
    currency: str
    budget_amount: float | None
    quantity: float | None
    unit_of_measure: str
    required_by_date: date | None
    preferred_supplier_mentioned: str | None
    incumbent_supplier: str | None
    delivery_countries: list[str]
    data_residency_constraint: bool
    esg_requirement: bool

    # Computed fields
    days_until_required: int | None = None
    preferred_supplier_id_resolved: str | None = None
    incumbent_supplier_id_resolved: str | None = None

    # LLM-populated (default empty / False — populated only if LLM succeeds)
    structured_checks: list[StructuredCheck] = field(default_factory=list)
    unknown_checks: list[UnknownCheck] = field(default_factory=list)
    subjective_criteria: list[SubjectiveCriterion] = field(default_factory=list)
    quantity_discrepancy: bool = False
    quantity_in_text: float | None = None
    llm_detected_language: str = "en"
    llm_parse_success: bool = False


# ---------------------------------------------------------------------------
# Phase 1 output
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    passed: bool
    reason: str | None = None
    escalations: list[Escalation] = field(default_factory=list)


@dataclass
class SupplierTrace:
    supplier_id: str
    supplier_name: str
    stages_passed: list[str] = field(default_factory=list)
    eliminated_at: str | None = None
    reason: str | None = None
    escalations: list[Escalation] = field(default_factory=list)
    pricing_tier: PricingTier | None = None   # cached by pricing_available check
    preference_discarded: bool = False
    preference_discard_reason: str = ""


# ---------------------------------------------------------------------------
# Phase 2 output
# ---------------------------------------------------------------------------

@dataclass
class ScoredSupplier:
    supplier_row: SupplierRow
    trace: SupplierTrace
    pricing_tier: PricingTier
    unit_price: float
    total_price: float
    expedited_unit_price: float
    expedited_total_price: float
    effective_lead_time: int        # standard or expedited, whichever is used
    using_expedited: bool
    composite_score: float
    score_breakdown: dict[str, float]
    is_preferred: bool
    is_incumbent: bool
    fit_rationale: str | None = None


# ---------------------------------------------------------------------------
# DataContext (passed to every function after load_data)
# ---------------------------------------------------------------------------

@dataclass
class DataContext:
    suppliers_by_category: dict[tuple[str, str], list[SupplierRow]]
    suppliers_by_id: dict[str, list[SupplierRow]]
    pricing_by_key: dict[tuple[str, str, str, str], list[PricingTier]]
    preferred_index: dict[tuple[str, str, str], dict]      # (sup_id, cat_l1, cat_l2)
    restricted_suppliers: list[dict]                        # small list; scan at query time
    approval_thresholds: list[ApprovalThreshold]
    category_rules: list[dict]
    geography_rules: list[dict]
    escalation_rules: dict[str, dict]                      # keyed by rule_id
    historical_by_request: dict[str, list[AwardRow]]
    historical_by_supplier_category: dict[tuple[str, str, str], list[AwardRow]]  # (supplier_id, cat_l1, cat_l2)
    categories: dict[tuple[str, str], CategoryRow]
