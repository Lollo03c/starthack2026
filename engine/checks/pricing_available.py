"""
Stage 7: Pricing Available
Find a valid pricing tier for this supplier/category/region/quantity/date.
Caches the found PricingTier on the SupplierTrace for Phase 2.

If quantity is None, fall back to tier for quantity=1 (minimum tier) with a note.
"""
from __future__ import annotations

from datetime import date

from engine.types import CheckResult, DataContext, RequestContext, SupplierRow


def check_pricing_available(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> CheckResult:
    from engine.data_loader import find_pricing_tier

    quantity = ctx.quantity if ctx.quantity is not None else 1.0
    delivery_country = ctx.delivery_countries[0] if ctx.delivery_countries else "DE"
    ref_date = date.today()

    tier = find_pricing_tier(
        data,
        supplier.supplier_id,
        ctx.category_l1,
        ctx.category_l2,
        delivery_country,
        quantity,
        ref_date,
    )

    if tier is None:
        return CheckResult(
            passed=False,
            reason=(
                f"No valid pricing available for {supplier.supplier_name} — "
                f"{ctx.category_l1}/{ctx.category_l2}, "
                f"region={delivery_country}, quantity={quantity:g}, date={ref_date}"
            ),
        )

    # Cache the tier on the trace — accessed in phase1_filter.py
    # This is done by attaching to CheckResult via a small sentinel approach:
    # phase1_filter reads result._pricing_tier if present.
    result = CheckResult(passed=True)
    result._pricing_tier = tier  # type: ignore[attr-defined]
    return result
