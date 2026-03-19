"""
Stage 1: Category Match
Verify the supplier covers the requested category_l1 + category_l2.
This is mostly a guard — candidates are pre-filtered by category before
entering the pipeline.
"""
from __future__ import annotations

from engine.types import CheckResult, DataContext, RequestContext, SupplierRow


def check_category_match(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> CheckResult:
    if (
        supplier.category_l1 == ctx.category_l1
        and supplier.category_l2 == ctx.category_l2
    ):
        return CheckResult(passed=True)
    return CheckResult(
        passed=False,
        reason=(
            f"Supplier does not offer {ctx.category_l1}/{ctx.category_l2} "
            f"(offers {supplier.category_l1}/{supplier.category_l2})"
        ),
    )
