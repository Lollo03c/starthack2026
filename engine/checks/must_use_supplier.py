"""
Stage 0: Hard supplier constraint enforcement.

If the request explicitly says a named supplier must be used, every other
supplier is eliminated before normal ranking. The mandated supplier itself
continues through the remaining checks.
"""
from __future__ import annotations

from engine.types import CheckResult, DataContext, RequestContext, SupplierRow


def check_must_use_supplier(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> CheckResult:
    del data

    if not ctx.supplier_must_use:
        return CheckResult(passed=True)
    if not ctx.preferred_supplier_id_resolved:
        preferred_name = ctx.preferred_supplier_mentioned or "the mandated supplier"
        return CheckResult(
            passed=False,
            reason=(
                f"User mandated supplier '{preferred_name}' only, but that supplier "
                "could not be matched to a known supplier record."
            ),
        )
    if supplier.supplier_id == ctx.preferred_supplier_id_resolved:
        return CheckResult(passed=True)

    preferred_name = ctx.preferred_supplier_mentioned or "the mandated supplier"
    return CheckResult(
        passed=False,
        reason=(
            f"User mandated supplier '{preferred_name}' only. "
            "Other suppliers are not allowed for this request."
        ),
    )
