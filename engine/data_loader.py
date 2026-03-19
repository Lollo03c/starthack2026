"""
Load all data files from the data/ directory into a DataContext.
Call load_data() once at startup and pass the result into every
process_request() call.

Handles all field-name inconsistencies in policies.json so the rest
of the codebase sees a clean, uniform schema.
"""
from __future__ import annotations

import csv
import json
import logging
import os
from datetime import date, datetime

from engine.types import (
    ApprovalThreshold,
    AwardRow,
    CategoryRow,
    DataContext,
    PricingTier,
    SupplierRow,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_data(data_dir: str) -> DataContext:
    """Load all CSV/JSON files from *data_dir* and return a DataContext.

    The DataContext is designed to be loaded once at startup and shared
    across requests.  All indexes are built here so lookups are O(1).
    """
    suppliers = _load_suppliers(os.path.join(data_dir, "suppliers.csv"))
    pricing   = _load_pricing(os.path.join(data_dir, "pricing.csv"))
    policies  = _load_policies(os.path.join(data_dir, "policies.json"))
    awards    = _load_awards(os.path.join(data_dir, "historical_awards.csv"))
    categories = _load_categories(os.path.join(data_dir, "categories.csv"))

    # --- suppliers_by_category index ---
    suppliers_by_category: dict[tuple[str, str], list[SupplierRow]] = {}
    suppliers_by_id: dict[str, list[SupplierRow]] = {}
    for s in suppliers:
        key = (s.category_l1, s.category_l2)
        suppliers_by_category.setdefault(key, []).append(s)
        suppliers_by_id.setdefault(s.supplier_id, []).append(s)

    # --- pricing_by_key index (sorted by min_quantity ascending) ---
    pricing_by_key: dict[tuple[str, str, str, str], list[PricingTier]] = {}
    for p in pricing:
        key = (p.supplier_id, p.category_l1, p.category_l2, p.region)
        pricing_by_key.setdefault(key, []).append(p)
    for tiers in pricing_by_key.values():
        tiers.sort(key=lambda t: t.min_quantity)

    # --- preferred_index ---
    preferred_index: dict[tuple[str, str, str], dict] = {}
    for entry in policies.get("preferred_suppliers", []):
        sid = entry.get("supplier_id", "")
        cat1 = entry.get("category_l1", "")
        cat2 = entry.get("category_l2", "")
        preferred_index[(sid, cat1, cat2)] = entry

    # --- historical awards by request ---
    historical_by_request: dict[str, list[AwardRow]] = {}
    for a in awards:
        historical_by_request.setdefault(a.request_id, []).append(a)

    # --- historical awards by supplier+category (for rationale lookup) ---
    historical_by_supplier_category: dict[tuple[str, str, str], list[AwardRow]] = {}
    for a in awards:
        key = (a.awarded_supplier_id, a.category_l1, a.category_l2)
        historical_by_supplier_category.setdefault(key, []).append(a)
    # Sort each list by award_date descending (most recent first)
    for lst in historical_by_supplier_category.values():
        lst.sort(key=lambda x: x.award_date, reverse=True)

    ctx = DataContext(
        suppliers_by_category=suppliers_by_category,
        suppliers_by_id=suppliers_by_id,
        pricing_by_key=pricing_by_key,
        preferred_index=preferred_index,
        restricted_suppliers=policies.get("restricted_suppliers", []),
        approval_thresholds=_build_approval_thresholds(
            policies.get("approval_thresholds", [])
        ),
        category_rules=_normalize_category_rules(
            policies.get("category_rules", [])
        ),
        geography_rules=_normalize_geography_rules(
            policies.get("geography_rules", [])
        ),
        escalation_rules=_build_escalation_rules(
            policies.get("escalation_rules", [])
        ),
        historical_by_request=historical_by_request,
        historical_by_supplier_category=historical_by_supplier_category,
        categories=categories,
    )

    logger.info(
        "DataContext loaded: %d supplier rows, %d pricing tiers, "
        "%d preferred entries, %d restrictions, %d approval thresholds",
        len(suppliers),
        len(pricing),
        len(preferred_index),
        len(ctx.restricted_suppliers),
        len(ctx.approval_thresholds),
    )
    return ctx


# ---------------------------------------------------------------------------
# Pricing tier lookup utility (used by checks and phase2_score)
# ---------------------------------------------------------------------------

def find_pricing_tier(
    data: DataContext,
    supplier_id: str,
    category_l1: str,
    category_l2: str,
    delivery_country: str,
    quantity: float,
    ref_date: date | None = None,
) -> PricingTier | None:
    """Return the applicable PricingTier for the given parameters, or None.

    Tries CH-specific pricing first for CH deliveries, then falls back to EU.
    Date validity is checked; pass ref_date=None to skip date check.
    """
    from engine.geo_utils import get_pricing_regions_for_country

    if ref_date is None:
        ref_date = date.today()

    for region in get_pricing_regions_for_country(delivery_country):
        tiers = data.pricing_by_key.get(
            (supplier_id, category_l1, category_l2, region), []
        )
        for tier in tiers:  # already sorted by min_quantity ascending
            if tier.min_quantity <= quantity <= tier.max_quantity:
                if tier.valid_from <= ref_date <= tier.valid_to:
                    return tier
    return None


def find_approval_threshold(
    data: DataContext,
    total_value: float,
    currency: str,
) -> ApprovalThreshold | None:
    """Return the matching ApprovalThreshold for a total contract value."""
    for threshold in data.approval_thresholds:
        if threshold.currency != currency:
            continue
        if threshold.min_amount <= total_value <= threshold.max_amount:
            return threshold
    return None


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

def _load_suppliers(path: str) -> list[SupplierRow]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            regions_raw = row.get("service_regions") or row.get("delivery_countries") or ""
            regions = frozenset(r.strip() for r in regions_raw.split(";") if r.strip())
            rows.append(SupplierRow(
                supplier_id=row["supplier_id"].strip(),
                supplier_name=row["supplier_name"].strip(),
                category_l1=row["category_l1"].strip(),
                category_l2=row["category_l2"].strip(),
                country_hq=row.get("country_hq", "").strip(),
                service_regions=regions,
                currency=row.get("currency", "EUR").strip(),
                pricing_model=row.get("pricing_model", "tiered").strip(),
                quality_score=_int(row.get("quality_score", 0)),
                risk_score=_int(row.get("risk_score", 0)),
                esg_score=_int(row.get("esg_score", 0)),
                preferred_supplier=_bool(row.get("preferred_supplier", "False")),
                is_restricted=_bool(row.get("is_restricted", "False")),
                restriction_reason=row.get("restriction_reason", "").strip(),
                contract_status=row.get("contract_status", "").strip(),
                data_residency_supported=_bool(
                    row.get("data_residency_supported", "False")
                ),
                capacity_per_month=_int(row.get("capacity_per_month", 999999)),
                notes=row.get("notes", "").strip(),
            ))
    return rows


def _load_pricing(path: str) -> list[PricingTier]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(PricingTier(
                pricing_id=row["pricing_id"].strip(),
                supplier_id=row["supplier_id"].strip(),
                category_l1=row["category_l1"].strip(),
                category_l2=row["category_l2"].strip(),
                region=row["region"].strip(),
                currency=row["currency"].strip(),
                pricing_model=row.get("pricing_model", "tiered").strip(),
                min_quantity=_float(row.get("min_quantity", 0)),
                max_quantity=_float(row.get("max_quantity", 999999)),
                unit_price=_float(row.get("unit_price", 0)),
                moq=_float(row.get("moq", 0)),
                standard_lead_time_days=_int(row.get("standard_lead_time_days", 0)),
                expedited_lead_time_days=_int(row.get("expedited_lead_time_days", 0)),
                expedited_unit_price=_float(row.get("expedited_unit_price", 0)),
                valid_from=_parse_date(row.get("valid_from", "2026-01-01")),
                valid_to=_parse_date(row.get("valid_to", "2026-12-31")),
                notes=row.get("notes", "").strip(),
            ))
    return rows


def _load_awards(path: str) -> list[AwardRow]:
    rows = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(AwardRow(
                    award_id=row.get("award_id", "").strip(),
                    request_id=row.get("request_id", "").strip(),
                    awarded_supplier_id=row.get("supplier_id", row.get("awarded_supplier_id", "")).strip(),
                    supplier_name=row.get("supplier_name", "").strip(),
                    category_l1=row.get("category_l1", "").strip(),
                    category_l2=row.get("category_l2", "").strip(),
                    award_rank=_int(row.get("award_rank", 1)),
                    award_date=row.get("award_date", "").strip(),
                    awarded=_bool(row.get("awarded", "False")),
                    total_award_value=_float(row.get("total_value", row.get("total_award_value", 0))),
                    currency=row.get("currency", "EUR").strip(),
                    decision_rationale=row.get("decision_rationale", "").strip(),
                    savings_pct=_float(row.get("savings_pct", 0)),
                    lead_time_days=_int(row.get("lead_time_days", 0)),
                    risk_score_at_award=_int(row.get("risk_score_at_award", 0)),
                    notes=row.get("notes", "").strip(),
                ))
    except FileNotFoundError:
        logger.warning("historical_awards.csv not found; skipping.")
    return rows


def _load_categories(path: str) -> dict[tuple[str, str], CategoryRow]:
    result: dict[tuple[str, str], CategoryRow] = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cat1 = row["category_l1"].strip()
                cat2 = row["category_l2"].strip()
                result[(cat1, cat2)] = CategoryRow(
                    category_l1=cat1,
                    category_l2=cat2,
                    description=row.get("category_description", "").strip(),
                    typical_unit=row.get("typical_unit", "unit").strip(),
                    pricing_model=row.get("pricing_model", "tiered").strip(),
                )
    except FileNotFoundError:
        logger.warning("categories.csv not found; skipping.")
    return result


# ---------------------------------------------------------------------------
# JSON loader
# ---------------------------------------------------------------------------

def _load_policies(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Normalisation helpers for policies.json inconsistencies
# ---------------------------------------------------------------------------

def _build_approval_thresholds(raw: list[dict]) -> list[ApprovalThreshold]:
    """Normalise EUR/CHF/USD field naming differences into ApprovalThreshold."""
    result = []
    for entry in raw:
        rule_id = entry.get("threshold_id") or entry.get("rule_id", "")
        currency = entry.get("currency", "EUR")

        # EUR/CHF use min_amount/max_amount; USD uses min_value/max_value
        min_amt = _float(
            entry.get("min_amount") or entry.get("min_value") or 0
        )
        max_raw = entry.get("max_amount") or entry.get("max_value")
        max_amt = float("inf") if max_raw is None else _float(max_raw)

        # quotes_required: EUR/CHF use min_supplier_quotes; USD uses quotes_required
        quotes = _int(
            entry.get("min_supplier_quotes") or entry.get("quotes_required") or 1
        )

        # approvers: EUR/CHF use managed_by (list); USD uses approvers (list)
        approvers_raw = entry.get("managed_by") or entry.get("approvers") or []
        if isinstance(approvers_raw, str):
            approvers_raw = [approvers_raw]

        # deviation_approval
        dev = (
            entry.get("deviation_approval_required_from")
            or entry.get("deviation_approval")
            or ""
        )
        if isinstance(dev, list):
            dev = ", ".join(dev)

        notes = entry.get("notes") or entry.get("policy_note") or ""

        result.append(ApprovalThreshold(
            rule_id=rule_id,
            currency=currency,
            min_amount=min_amt,
            max_amount=max_amt,
            quotes_required=quotes,
            approvers=list(approvers_raw),
            deviation_approval=str(dev),
            notes=str(notes),
        ))
    return result


def _normalize_category_rules(raw: list[dict]) -> list[dict]:
    """Return category_rules as-is; they are structurally consistent."""
    return list(raw)


def _normalize_geography_rules(raw: list[dict]) -> list[dict]:
    """Normalise GR-001–004 (single 'country' field) vs GR-005–008 ('countries' list)."""
    result = []
    for entry in raw:
        entry = dict(entry)  # shallow copy
        # Normalise country → countries list
        if "country" in entry and "countries" not in entry:
            entry["countries"] = [entry["country"]]
        elif "countries" not in entry:
            entry["countries"] = []
        # Normalise 'rule' → 'rule_text'
        if "rule" in entry and "rule_text" not in entry:
            entry["rule_text"] = entry.pop("rule")
        result.append(entry)
    return result


def _build_escalation_rules(raw) -> dict[str, dict]:
    """Build dict keyed by rule_id from either a list or existing dict.
    Normalises the field name inconsistency for ER-008."""
    result: dict[str, dict] = {}
    if isinstance(raw, dict):
        items = raw.values()
    else:
        items = raw
    for entry in items:
        entry = dict(entry)
        # ER-008 uses escalation_target instead of escalate_to
        if "escalation_target" in entry and "escalate_to" not in entry:
            entry["escalate_to"] = entry.pop("escalation_target")
        rule_id = entry.get("rule_id", "")
        if rule_id:
            result[rule_id] = entry
    return result


# ---------------------------------------------------------------------------
# Primitive parsers
# ---------------------------------------------------------------------------

def _int(value) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _float(value) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return date(2026, 1, 1)
