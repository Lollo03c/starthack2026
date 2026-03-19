"""
Stage 0: Hard supplier constraint enforcement.

If the request explicitly says a named supplier must be used, we keep the
mandated supplier requirement for recommendation logic and escalation logic,
but we do NOT eliminate all other suppliers. Alternatives still need to be
ranked so the user can explicitly approve a switch.
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
    return CheckResult(passed=True)
