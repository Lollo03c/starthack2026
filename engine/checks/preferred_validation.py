"""
Stage 5: Preferred Supplier Validation
Validates whether the stated preferred supplier preference is achievable.
Does NOT eliminate non-preferred suppliers — only adds metadata to the trace.

The SupplierTrace.preference_discarded flag is set via CheckResult extras when
the preferred supplier fails validation.  All suppliers return passed=True.
"""
from __future__ import annotations

from engine.types import CheckResult, DataContext, Escalation, RequestContext, SupplierRow


def check_preferred_validation(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> CheckResult:
    # Only act if there is a stated preference and we resolved it to an ID
    if not ctx.preferred_supplier_mentioned or not ctx.preferred_supplier_id_resolved:
        return CheckResult(passed=True)

    # Only perform validation against the preferred supplier itself
    if supplier.supplier_id != ctx.preferred_supplier_id_resolved:
        return CheckResult(passed=True)

    escalations: list[Escalation] = []

    # Check 1: Does the preferred supplier offer this category?
    key = (supplier.supplier_id, ctx.category_l1, ctx.category_l2)
    preferred_entry = data.preferred_index.get(key)

    # Check category via suppliers_by_id
    sup_rows = data.suppliers_by_id.get(supplier.supplier_id, [])
    has_category = any(
        r.category_l1 == ctx.category_l1 and r.category_l2 == ctx.category_l2
        for r in sup_rows
    )

    if not has_category:
        escalations.append(Escalation(
            rule_id="ER-004",
            trigger=(
                f"Preferred supplier '{ctx.preferred_supplier_mentioned}' does not offer "
                f"{ctx.category_l1}/{ctx.category_l2}. Preference discarded."
            ),
            escalate_to="Head of Category",
            blocking=False,
        ))
        # Signal discard via a special field — handled in phase1_filter
        return CheckResult(
            passed=True,
            reason="PREFERENCE_DISCARDED:category_mismatch",
            escalations=escalations,
        )

    # Check 2: Does the preferred supplier cover the delivery countries?
    required = set(ctx.delivery_countries)
    missing = required - supplier.service_regions
    if missing:
        missing_str = ", ".join(sorted(missing))
        escalations.append(Escalation(
            rule_id="ER-004",
            trigger=(
                f"Preferred supplier '{ctx.preferred_supplier_mentioned}' does not serve "
                f"delivery country/countries: {missing_str}. Preference discarded."
            ),
            escalate_to="Head of Category",
            blocking=False,
        ))
        return CheckResult(
            passed=True,
            reason="PREFERENCE_DISCARDED:region_mismatch",
            escalations=escalations,
        )

    # Check 3: Region scope on the preferred_index entry
    if preferred_entry is not None:
        region_scope = preferred_entry.get("region_scope")
        if region_scope:
            from engine.geo_utils import country_to_region
            request_regions = {country_to_region(c) for c in ctx.delivery_countries}
            if not (request_regions & set(region_scope)):
                escalations.append(Escalation(
                    rule_id="ER-004",
                    trigger=(
                        f"Preferred supplier '{ctx.preferred_supplier_mentioned}' is not "
                        f"preferred in region(s) {request_regions} "
                        f"(preferred scope: {region_scope}). Preference not applicable."
                    ),
                    escalate_to="Head of Category",
                    blocking=False,
                ))
                return CheckResult(
                    passed=True,
                    reason="PREFERENCE_DISCARDED:region_scope",
                    escalations=escalations,
                )

    return CheckResult(passed=True, escalations=escalations)
