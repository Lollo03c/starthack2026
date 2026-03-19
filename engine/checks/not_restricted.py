"""
Stage 4: Not Restricted
Authoritative source: policies.json restricted_suppliers list.
The is_restricted flag in suppliers.csv is a hint only.

Restriction types:
- scope ["all"]          → always applies
- scope [country codes]  → applies if any delivery_country is in scope
- value-conditional      → check against budget_amount via config.CONDITIONAL_RESTRICTION_THRESHOLDS
"""
from __future__ import annotations

from engine import config
from engine.types import CheckResult, DataContext, Escalation, RequestContext, SupplierRow


def check_not_restricted(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> CheckResult:
    for entry in data.restricted_suppliers:
        if not _entry_matches_supplier(entry, supplier, ctx):
            continue

        # Entry matches this supplier + category — evaluate scope
        scope: list[str] = entry.get("restriction_scope") or entry.get("scope") or ["all"]
        applies = _scope_applies(scope, ctx.delivery_countries)

        if not applies:
            continue

        # Check for value-conditional restriction
        conditional = _get_conditional_threshold(supplier.supplier_id, ctx.category_l2)
        if conditional is not None:
            result = _handle_conditional(conditional, supplier, entry, ctx)
            return result

        # Hard restriction applies
        reason_text = entry.get("restriction_reason") or entry.get("reason") or "Policy restriction"
        esc = Escalation(
            rule_id="ER-002",
            trigger=(
                f"Supplier {supplier.supplier_name} is restricted for "
                f"{ctx.category_l1}/{ctx.category_l2} "
                f"(scope: {scope}). Reason: {reason_text}"
            ),
            escalate_to="Procurement Manager",
            blocking=True,
        )
        return CheckResult(
            passed=False,
            reason=(
                f"Restricted for {ctx.category_l1}/{ctx.category_l2} "
                f"in delivery context {ctx.delivery_countries}. "
                f"Reason: {reason_text}"
            ),
            escalations=[esc],
        )

    return CheckResult(passed=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_matches_supplier(
    entry: dict,
    supplier: SupplierRow,
    ctx: RequestContext,
) -> bool:
    """True if a restriction entry applies to this supplier + category."""
    if entry.get("supplier_id") != supplier.supplier_id:
        return False

    entry_cat1 = entry.get("category_l1", "")
    entry_cat2 = entry.get("category_l2", "")

    # Some entries specify category; empty means all categories
    if entry_cat1 and entry_cat1 != ctx.category_l1:
        return False
    if entry_cat2 and entry_cat2 != ctx.category_l2:
        return False

    return True


def _scope_applies(scope: list[str], delivery_countries: list[str]) -> bool:
    """True if the restriction scope applies to the given delivery countries."""
    if not scope or scope == ["all"]:
        return True
    # scope is a list of country codes — applies if any delivery country is in scope
    delivery_set = set(delivery_countries)
    return bool(delivery_set & set(scope))


def _get_conditional_threshold(supplier_id: str, category_l2: str) -> dict | None:
    """Return conditional restriction config for this supplier+category, or None."""
    sup_entry = config.CONDITIONAL_RESTRICTION_THRESHOLDS.get(supplier_id)
    if sup_entry is None:
        return None
    return sup_entry.get(category_l2)


def _handle_conditional(
    threshold_cfg: dict,
    supplier: SupplierRow,
    entry: dict,
    ctx: RequestContext,
) -> CheckResult:
    """Handle a value-conditional restriction (e.g. SUP-0045 EUR 75K threshold)."""
    threshold = threshold_cfg["threshold"]
    currency = threshold_cfg["currency"]

    if ctx.budget_amount is None:
        # No budget specified — no constraint applied; recorded as assumption, not escalation
        return CheckResult(passed=True)

    if ctx.budget_amount >= threshold:
        reason_text = entry.get("restriction_reason") or "Value-conditional restriction"
        esc = Escalation(
            rule_id="ER-002",
            trigger=(
                f"Supplier {supplier.supplier_name} is restricted for contracts "
                f"at or above {currency} {threshold:,.0f}. "
                f"Stated budget {ctx.currency} {ctx.budget_amount:,.2f} meets or exceeds threshold."
            ),
            escalate_to="Procurement Manager",
            blocking=True,
        )
        return CheckResult(
            passed=False,
            reason=(
                f"Value-conditional restriction applies: budget {ctx.budget_amount:,.2f} "
                f">= threshold {threshold:,.0f} {currency}. {reason_text}"
            ),
            escalations=[esc],
        )

    # Budget is below threshold — restriction does not apply
    return CheckResult(passed=True)
