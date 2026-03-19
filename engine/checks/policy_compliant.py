"""
Stage 6: Policy Compliance
Applies category_rules and geography_rules from policies.json.

Only one rule causes hard elimination:
  CR-004 — data_residency_constraint=True AND supplier.data_residency_supported=False

All other rules add non-blocking escalations or notes.
"""
from __future__ import annotations

import re

from engine.types import CheckResult, DataContext, Escalation, RequestContext, SupplierRow

# Escalation targets by rule type
_ESCALATE_BY_RULE_TYPE: dict[str, str] = {
    "mandatory_comparison":   "Procurement Manager",
    "engineering_spec_review": "Head of Category",
    "fast_track":              "Procurement Manager",
    "residency_check":         "Security / Compliance",
    "security_review":         "Head of Category",
    "design_signoff":          "Business",
    "cv_review":               "Head of Category",
    "certification_check":     "Head of Category",
    "performance_baseline":    "Head of Category",
    "brand_safety":            "Marketing Governance Lead",
}


def check_policy_compliant(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> CheckResult:
    escalations: list[Escalation] = []

    # --- Category rules -------------------------------------------------------
    for rule in data.category_rules:
        result = _apply_category_rule(rule, supplier, ctx)
        if result is None:
            continue
        if result == "FAIL_DATA_RESIDENCY":
            return CheckResult(
                passed=False,
                reason=(
                    f"Data residency constraint required but supplier "
                    f"{supplier.supplier_name} does not support data residency (CR-004)."
                ),
                escalations=escalations,
            )
        escalations.append(result)

    # --- Geography rules (run once per request, not per supplier) -------------
    # To avoid duplicate geo-rule escalations across suppliers, we only add them
    # for the first supplier alphabetically (or unconditionally — deduplication
    # in output_builder handles the rest).
    for rule in data.geography_rules:
        esc = _apply_geography_rule(rule, ctx)
        if esc is not None:
            escalations.append(esc)

    return CheckResult(passed=True, escalations=escalations)


# ---------------------------------------------------------------------------
# Category rule handlers
# ---------------------------------------------------------------------------

def _apply_category_rule(
    rule: dict,
    supplier: SupplierRow,
    ctx: RequestContext,
) -> "Escalation | str | None":
    """Return an Escalation, 'FAIL_DATA_RESIDENCY', or None if rule doesn't apply."""
    rule_id = rule.get("rule_id", "")
    cat1 = rule.get("category_l1", "")
    cat2 = rule.get("category_l2", "")
    rule_type = rule.get("rule_type", "")
    rule_text = rule.get("rule_text", "")
    escalate_to = _ESCALATE_BY_RULE_TYPE.get(rule_type, "Procurement Manager")

    # Check if rule applies to this request's category
    if cat1 and cat1 != ctx.category_l1:
        return None
    if cat2 and cat2 != ctx.category_l2:
        return None

    # CR-004: data residency check (hard elimination per supplier)
    if rule_id == "CR-004" or rule_type == "residency_check":
        if ctx.data_residency_constraint and not supplier.data_residency_supported:
            return "FAIL_DATA_RESIDENCY"
        return None  # rule applies to category but condition not met for this supplier

    # Check if the threshold condition in rule_text is met
    if not _threshold_met(rule_text, ctx):
        return None

    # ER-007: brand_safety rules use escalation rule ER-007 instead of the category rule ID
    if rule_type == "brand_safety":
        return Escalation(
            rule_id="ER-007",
            trigger=f"Brand safety review required ({rule_id}): {rule_text}",
            escalate_to="Marketing Governance Lead",
            blocking=False,
        )

    return Escalation(
        rule_id=rule_id,
        trigger=f"Category rule {rule_id}: {rule_text}",
        escalate_to=escalate_to,
        blocking=False,
    )


def _threshold_met(rule_text: str, ctx: RequestContext) -> bool:
    """Return True if the threshold condition in rule_text is satisfied."""
    text_lower = rule_text.lower()

    # Find any numeric threshold in the text
    # Patterns like "above EUR/CHF 100000", "above 50 units", "below EUR/CHF 75000"
    above_match = re.search(r'above\s+(?:eur/chf|eur|chf|usd)?\s*([\d,]+)', text_lower)
    below_match = re.search(r'below\s+(?:eur/chf|eur|chf|usd)?\s*([\d,]+)', text_lower)

    if above_match:
        threshold = float(above_match.group(1).replace(",", ""))
        # Is this a value threshold or a quantity threshold?
        if "unit" in text_lower or "days" in text_lower:
            qty = ctx.quantity or 0
            return qty > threshold
        else:
            if ctx.budget_amount is None:
                return False  # no budget — skip value-threshold rule, noted as assumption
            return ctx.budget_amount > threshold

    if below_match:
        threshold = float(below_match.group(1).replace(",", ""))
        if "unit" in text_lower or "days" in text_lower:
            qty = ctx.quantity or 0
            return qty < threshold
        else:
            if ctx.budget_amount is None:
                return False  # no budget — skip value-threshold rule, noted as assumption
            return ctx.budget_amount < threshold

    # No threshold — rule always applies to the matching category
    return True


# ---------------------------------------------------------------------------
# Geography rule handler
# ---------------------------------------------------------------------------

def _apply_geography_rule(rule: dict, ctx: RequestContext) -> "Escalation | None":
    """Return an Escalation if the geography rule applies, else None."""
    rule_id = rule.get("rule_id", "")
    countries: list[str] = rule.get("countries") or []
    rule_text = rule.get("rule_text") or rule.get("action", "")
    escalate_to = "Procurement Manager"

    # Check country match
    delivery_set = set(ctx.delivery_countries)
    if countries and not (delivery_set & set(countries)):
        return None

    # Some geo rules only apply to specific categories/types
    rule_type = rule.get("rule_type", "")
    if rule_type == "sovereign_preference":
        # Only relevant if data_residency_constraint is set or cloud category
        if not ctx.data_residency_constraint and ctx.category_l1 != "IT":
            return None
        if ctx.category_l2 not in (
            "Cloud Compute", "Cloud Storage", "Cloud Networking",
            "Managed Cloud Platform Services", "Cloud Security Services"
        ):
            return None
    elif rule_type == "lead_time_constraint":
        # Only for urgent device requests
        if ctx.days_until_required is None or ctx.days_until_required > 14:
            return None
        if ctx.category_l1 != "IT":
            return None

    return Escalation(
        rule_id=rule_id,
        trigger=f"Geography rule {rule_id} triggered for delivery to {ctx.delivery_countries}: {rule_text}",
        escalate_to=escalate_to,
        blocking=False,
    )
