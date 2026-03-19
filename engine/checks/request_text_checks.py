"""
Stage 8: Request Text Checks
Execute structured_checks and unknown_checks produced by Phase 0 LLM decomposition.

- If LLM was disabled or failed, both lists are empty → always passes immediately.
- structured_checks: run against known supplier fields; mismatch → add note (no elimination).
- unknown_checks: cannot be verified deterministically → add non-blocking escalation.
"""
from __future__ import annotations

from engine.types import CheckResult, DataContext, Escalation, RequestContext, SupplierRow


def check_request_text(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> CheckResult:
    if not ctx.structured_checks and not ctx.unknown_checks:
        return CheckResult(passed=True)

    escalations: list[Escalation] = []

    # --- Structured checks (verifiable against supplier fields) ---------------
    for sc in ctx.structured_checks:
        esc = _run_structured_check(sc, supplier, ctx)
        if esc:
            escalations.append(esc)

    # --- Unknown checks (not verifiable — escalate for manual review) ---------
    for uc in ctx.unknown_checks:
        escalations.append(Escalation(
            rule_id="ER-004",
            trigger=(
                f"Request text check not verifiable: '{uc.check}' — "
                f"{uc.description}. Manual verification required."
            ),
            escalate_to="Head of Category",
            blocking=False,
        ))

    return CheckResult(passed=True, escalations=escalations)


# ---------------------------------------------------------------------------
# Structured check runner
# ---------------------------------------------------------------------------

_SUPPLIER_FIELD_MAP: dict[str, str] = {
    "data_residency": "data_residency_supported",
    "data_residency_supported": "data_residency_supported",
    "preferred": "preferred_supplier",
    "preferred_supplier": "preferred_supplier",
    "contract_status": "contract_status",
    "quality_score": "quality_score",
    "esg_score": "esg_score",
    "risk_score": "risk_score",
    "capacity": "capacity_per_month",
    "capacity_per_month": "capacity_per_month",
}


def _run_structured_check(
    sc,
    supplier: SupplierRow,
    ctx: RequestContext,
) -> "Escalation | None":
    """Try to verify a structured check against the supplier.

    Returns an escalation if the check fails, None if it passes or is not verifiable.
    """
    field_name = _SUPPLIER_FIELD_MAP.get(sc.check.lower())
    if field_name is None:
        # Field not in our mapping → treat as unknown
        return Escalation(
            rule_id="ER-004",
            trigger=(
                f"Structured check '{sc.check}' could not be mapped to a supplier field. "
                "Manual verification required."
            ),
            escalate_to="Head of Category",
            blocking=False,
        )

    actual = getattr(supplier, field_name, None)
    if actual is None:
        return None  # field doesn't exist on supplier; skip

    expected = sc.value
    operator = (sc.operator or "eq").lower()

    try:
        if operator == "eq":
            passed = str(actual).lower() == str(expected).lower()
        elif operator == "gte":
            passed = float(actual) >= float(expected)
        elif operator == "lte":
            passed = float(actual) <= float(expected)
        elif operator == "contains":
            passed = str(expected).lower() in str(actual).lower()
        else:
            passed = True  # unknown operator — skip
    except (TypeError, ValueError):
        passed = True  # can't compare — skip

    if not passed:
        return Escalation(
            rule_id="ER-004",
            trigger=(
                f"Structured check failed for {supplier.supplier_name}: "
                f"{sc.check} expected {operator} {expected!r}, got {actual!r}."
            ),
            escalate_to="Head of Category",
            blocking=False,
        )
    return None
