"""
Stage 3: Quantity Feasibility
- quantity is None → escalate ER-001 (missing info), still pass
- quantity > capacity_per_month → escalate ER-006 (non-blocking), still pass
- quantity < MOQ from pricing tier → FAIL
"""
from __future__ import annotations

from datetime import date

from engine.types import CheckResult, DataContext, Escalation, RequestContext, SupplierRow


def check_quantity_feasible(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> CheckResult:
    escalations: list[Escalation] = []

    if ctx.quantity is None:
        escalations.append(Escalation(
            rule_id="ER-001",
            trigger="Request quantity is missing. Cannot verify quantity feasibility.",
            escalate_to="Requester",
            blocking=False,
        ))
        return CheckResult(passed=True, escalations=escalations)

    qty = ctx.quantity

    # Capacity check (non-blocking — supplier is not eliminated)
    if supplier.capacity_per_month > 0 and qty > supplier.capacity_per_month:
        escalations.append(Escalation(
            rule_id="ER-006",
            trigger=(
                f"Requested quantity {qty:g} exceeds {supplier.supplier_name}'s "
                f"monthly capacity of {supplier.capacity_per_month:,}. "
                "Supplier can still be evaluated but fulfilment risk is high."
            ),
            escalate_to="Sourcing Excellence Lead",
            blocking=False,
        ))

    # MOQ check — find any pricing tier for this supplier + category + any delivery country
    from engine.data_loader import find_pricing_tier
    ref_date = date.today()
    delivery_country = ctx.delivery_countries[0] if ctx.delivery_countries else "DE"
    tier = find_pricing_tier(
        data,
        supplier.supplier_id,
        ctx.category_l1,
        ctx.category_l2,
        delivery_country,
        qty,
        ref_date,
    )

    if tier is not None and tier.moq > 0 and qty < tier.moq:
        return CheckResult(
            passed=False,
            reason=(
                f"Requested quantity {qty:g} is below the minimum order quantity "
                f"(MOQ) of {tier.moq:g} for {supplier.supplier_name}."
            ),
            escalations=escalations,
        )

    return CheckResult(passed=True, escalations=escalations)
