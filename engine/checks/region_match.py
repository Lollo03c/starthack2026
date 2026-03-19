"""
Stage 2: Region Match
All delivery countries in the request must be served by the supplier.
"""
from __future__ import annotations

from engine.types import CheckResult, DataContext, RequestContext, SupplierRow


def check_region_match(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> CheckResult:
    required = set(ctx.delivery_countries)
    if not required:
        # No delivery country specified — pass (we can't filter)
        return CheckResult(passed=True)

    missing = required - supplier.service_regions
    if missing:
        missing_str = ", ".join(sorted(missing))
        return CheckResult(
            passed=False,
            reason=f"Supplier does not serve delivery country/countries: {missing_str}",
        )
    return CheckResult(passed=True)
