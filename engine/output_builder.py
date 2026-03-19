"""
Output Builder: assemble all pipeline outputs into the final JSON dict.

This is the only place where sequential IDs (ESC-001, V-001) are assigned.
The schema must match examples/example_output.json.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from engine import config
from engine.data_loader import find_approval_threshold
from engine.fx import convert as fx_convert
from engine.types import (
    DataContext,
    Escalation,
    RequestContext,
    ScoredSupplier,
    SupplierTrace,
    Uncertainty,
)

logger = logging.getLogger(__name__)


def build_output(
    request_dict: dict,
    ctx: RequestContext,
    scored: list[ScoredSupplier],
    eliminated: list[SupplierTrace],
    data: DataContext,
) -> dict:
    """Assemble the final output JSON matching the example schema."""

    # --- Validation issues ----------------------------------------------------
    validation_issues = _detect_validation_issues(ctx, scored, eliminated)
    # Assign V-xxx IDs: critical first, then high, then medium
    _assign_validation_ids(validation_issues)

    # --- Escalations ----------------------------------------------------------
    raw_escalations = _collect_escalations(scored, eliminated, ctx, validation_issues, data)
    deduped_escalations = _deduplicate_escalations(raw_escalations)
    overrides = request_dict.get("escalation_overrides") or {}
    if overrides:
        deduped_escalations = _apply_escalation_overrides(deduped_escalations, overrides)
    _assign_escalation_ids(deduped_escalations)

    # --- Recommendation -------------------------------------------------------
    recommendation = _build_recommendation(ctx, scored, validation_issues, deduped_escalations)

    # --- Policy evaluation ----------------------------------------------------
    policy_eval = _build_policy_evaluation(ctx, scored, eliminated, data)

    # --- Shortlist and excluded -----------------------------------------------
    shortlist = scored[: config.SHORTLIST_MAX]
    not_ranked = scored[config.SHORTLIST_MAX :]

    # --- Uncertainties --------------------------------------------------------
    uncertainties = _detect_uncertainties(ctx, scored, eliminated, data)
    formatted_uncertainties = []
    for i, u in enumerate(uncertainties):
        formatted_uncertainties.append({
            "id": f"U-{i + 1:03d}",
            "type": u.uncertainty_type,
            "source": u.source,
            "description": u.description,
            "assumption_made": u.assumption_made,
            "impact": u.impact,
            "requires_approval": u.requires_approval,
        })

    # --- FX conversion context for interpretation and shortlist ---------------
    fx_info = _compute_fx_info(ctx, scored)

    # --- Audit trail ----------------------------------------------------------
    audit_trail = _build_audit_trail(ctx, scored, eliminated, data, validation_issues, deduped_escalations)

    interpretation = _build_interpretation(ctx)
    if fx_info:
        interpretation.update(fx_info["interpretation_extra"])

    return {
        "request_id": ctx.request_id,
        "processed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "request_interpretation": interpretation,
        "validation": {
            "completeness": "fail" if validation_issues else "pass",
            "issues_detected": [_format_issue(v) for v in validation_issues],
        },
        "policy_evaluation": policy_eval,
        "supplier_shortlist": [_format_scored(s, i + 1, fx_info) for i, s in enumerate(shortlist)],
        "suppliers_excluded": (
            [_format_eliminated(t) for t in eliminated]
            + [_format_scored_excluded(s) for s in not_ranked]
        ),
        "escalations": [_format_escalation(e) for e in deduped_escalations],
        "uncertainties": formatted_uncertainties,
        "recommendation": recommendation,
        "audit_trail": audit_trail,
    }


# ---------------------------------------------------------------------------
# Interpretation
# ---------------------------------------------------------------------------

def _build_interpretation(ctx: RequestContext) -> dict:
    days = ctx.days_until_required
    return {
        "category_l1": ctx.category_l1,
        "category_l2": ctx.category_l2,
        "quantity": ctx.quantity,
        "unit_of_measure": ctx.unit_of_measure,
        "budget_amount": ctx.budget_amount,
        "currency": ctx.currency,
        "delivery_countries": ctx.delivery_countries,
        "required_by_date": ctx.required_by_date.isoformat() if ctx.required_by_date else None,
        "days_until_required": days,
        "data_residency_required": ctx.data_residency_constraint,
        "esg_requirement": ctx.esg_requirement,
        "preferred_supplier_stated": ctx.preferred_supplier_mentioned,
        "preferred_supplier_resolved_id": ctx.preferred_supplier_id_resolved,
        "incumbent_supplier": ctx.incumbent_supplier,
        "quantity_discrepancy_detected": ctx.quantity_discrepancy,
        "quantity_in_text": ctx.quantity_in_text if ctx.quantity_discrepancy else None,
        "llm_parse_success": ctx.llm_parse_success,
        "detected_language": ctx.llm_detected_language,
    }


# ---------------------------------------------------------------------------
# Validation issues
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2}


class ValidationIssue:
    def __init__(self, issue_type: str, severity: str, description: str, action_required: str):
        self.issue_id: str = ""
        self.issue_type = issue_type
        self.severity = severity
        self.description = description
        self.action_required = action_required


def _detect_validation_issues(
    ctx: RequestContext,
    scored: list[ScoredSupplier],
    eliminated: list[SupplierTrace],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    # 1. Missing quantity
    if ctx.quantity is None:
        issues.append(ValidationIssue(
            "missing_quantity", "high",
            "Request quantity field is null.",
            "Requester must provide the required quantity before sourcing can proceed.",
        ))

    # 2. Missing budget
    if ctx.budget_amount is None:
        issues.append(ValidationIssue(
            "missing_budget", "high",
            "Request budget amount field is null.",
            "Requester must provide a budget amount to enable supplier pricing validation.",
        ))

    # 3. Quantity text mismatch
    if ctx.quantity_discrepancy and ctx.quantity_in_text is not None:
        issues.append(ValidationIssue(
            "quantity_text_mismatch", "medium",
            (
                f"Quantity field ({ctx.quantity:g}) differs from quantity mentioned in "
                f"request text ({ctx.quantity_in_text:g}) by more than "
                f"{config.QUANTITY_DISCREPANCY_THRESHOLD * 100:.0f}%."
            ),
            "Requester should confirm the intended quantity.",
        ))

    # 4. Budget insufficient (only if budget AND quantity are set, same currency, and we have priced candidates)
    same_currency_scored = [s for s in scored if s.pricing_tier.currency == ctx.currency]
    if ctx.budget_amount is not None and ctx.quantity and same_currency_scored:
        min_total = min(s.pricing_tier.unit_price * ctx.quantity for s in same_currency_scored)
        tolerance = ctx.budget_amount * (1 + config.BUDGET_TOLERANCE_FRACTION)
        if min_total > tolerance:
            cheapest = min(same_currency_scored, key=lambda s: s.pricing_tier.unit_price)
            issues.append(ValidationIssue(
                "budget_insufficient", "critical",
                (
                    f"Budget of {ctx.currency} {ctx.budget_amount:,.2f} cannot cover "
                    f"{ctx.quantity:g} units at any compliant supplier's standard pricing. "
                    f"Lowest available unit price is {ctx.currency} "
                    f"{cheapest.pricing_tier.unit_price:,.2f} "
                    f"({cheapest.supplier_row.supplier_name}), yielding a minimum total of "
                    f"{ctx.currency} {min_total:,.2f}."
                ),
                (
                    f"Requester must either increase budget to at least "
                    f"{ctx.currency} {min_total:,.2f} or reduce quantity."
                ),
            ))

    # 5. Lead time infeasible
    if ctx.days_until_required is not None and scored:
        min_expedited = min(s.pricing_tier.expedited_lead_time_days for s in scored)
        if ctx.days_until_required < min_expedited:
            issues.append(ValidationIssue(
                "lead_time_infeasible", "high",
                (
                    f"Required delivery date is {ctx.days_until_required} day(s) away. "
                    f"All suppliers' expedited lead times exceed this "
                    f"(minimum expedited: {min_expedited} days)."
                ),
                "Requester must confirm whether the delivery date is a hard constraint. "
                "If so, no compliant supplier can meet it.",
            ))

    # 6. Policy conflict: requester instruction that contradicts mandatory policy
    if ctx.request_text and scored:
        _detect_policy_conflicts(ctx, scored, issues)

    # 7. Preferred supplier restricted
    if ctx.preferred_supplier_mentioned and ctx.preferred_supplier_id_resolved:
        for trace in eliminated:
            if (
                trace.supplier_id == ctx.preferred_supplier_id_resolved
                and trace.eliminated_at == "not_restricted"
            ):
                issues.append(ValidationIssue(
                    "preferred_supplier_restricted", "high",
                    f"The stated preferred supplier '{ctx.preferred_supplier_mentioned}' "
                    f"is restricted for this category/region combination.",
                    "Escalation to Procurement Manager is required.",
                ))
                break

    # 8. No compliant suppliers
    if not scored:
        issues.append(ValidationIssue(
            "no_compliant_suppliers", "critical",
            f"No suppliers passed all Phase 1 filters for "
            f"{ctx.category_l1}/{ctx.category_l2} "
            f"in delivery context {ctx.delivery_countries}.",
            "Escalation to Head of Category is required to identify alternative supply options.",
        ))

    return issues


def _detect_policy_conflicts(
    ctx: RequestContext,
    scored: list[ScoredSupplier],
    issues: list[ValidationIssue],
) -> None:
    """Detect when request text instructions contradict mandatory policies."""
    text_lower = ctx.request_text.lower()

    # "No exception" or single-supplier instruction + value requiring multiple quotes
    single_source_phrases = ["no exception", "only", "exclusively", "no alternative", "sole source"]
    has_single_source = any(p in text_lower for p in single_source_phrases)

    if has_single_source and scored:
        # Check if the contract value requires multiple quotes
        min_total = min(s.total_price for s in scored)
        from engine.data_loader import find_approval_threshold
        from engine.types import DataContext
        # Use the first scored supplier's currency
        currency = ctx.currency
        # We need data here — look up threshold
        # We can't easily access data here, so we check a common threshold (EUR 25K for AT-002)
        # The full check is done in policy_evaluation; here we just flag the linguistic conflict
        issues.append(ValidationIssue(
            "policy_conflict", "high",
            (
                "Request text contains a single-supplier instruction "
                f"('{[p for p in single_source_phrases if p in text_lower][0]}'). "
                "Procurement policy may require multiple quotes depending on contract value. "
                f"Minimum estimated contract value: {currency} {min_total:,.2f}."
            ),
            "Verify whether the applicable approval threshold allows single-source selection. "
            "If not, at least 2 quotes are required unless a deviation is approved.",
        ))


def _assign_validation_ids(issues: list[ValidationIssue]) -> None:
    issues.sort(key=lambda v: _SEVERITY_ORDER.get(v.severity, 99))
    for i, issue in enumerate(issues):
        issue.issue_id = f"V-{i + 1:03d}"


def _format_issue(v: ValidationIssue) -> dict:
    return {
        "issue_id": v.issue_id,
        "severity": v.severity,
        "type": v.issue_type,
        "description": v.description,
        "action_required": v.action_required,
    }


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------

def _collect_escalations(
    scored: list[ScoredSupplier],
    eliminated: list[SupplierTrace],
    ctx: RequestContext,
    validation_issues: list[ValidationIssue],
    data: DataContext,
) -> list[Escalation]:
    all_esc: list[Escalation] = []

    for s in scored:
        all_esc.extend(s.trace.escalations)
    for t in eliminated:
        all_esc.extend(t.escalations)

    # Add escalations for validation issues that require human action
    for issue in validation_issues:
        if issue.issue_type in {"budget_insufficient", "missing_quantity", "missing_budget"}:
            all_esc.append(Escalation(
                rule_id="ER-001",
                trigger=issue.description,
                escalate_to="Requester",
                blocking=True,
            ))
        elif issue.issue_type == "no_compliant_suppliers":
            all_esc.append(Escalation(
                rule_id="ER-004",
                trigger=issue.description,
                escalate_to="Head of Category",
                blocking=True,
            ))
        elif issue.issue_type == "lead_time_infeasible":
            all_esc.append(Escalation(
                rule_id="ER-004",
                trigger=issue.description,
                escalate_to="Head of Category",
                blocking=True,
            ))

    # --- A1: ER-003 (value_exceeds_threshold) — high-value contracts ----------
    if scored:
        min_total = min(s.total_price for s in scored)
        threshold = find_approval_threshold(data, min_total, ctx.currency)

        # ER-003: fire when value hits the high tiers (500K+ EUR/CHF, 540K+ USD)
        high_value_tiers = {
            "EUR": 500_000, "CHF": 500_000, "USD": 540_000,
        }
        hv_floor = high_value_tiers.get(ctx.currency)
        if hv_floor is not None and min_total >= hv_floor:
            all_esc.append(Escalation(
                rule_id="ER-003",
                trigger=(
                    f"Estimated contract value {ctx.currency} {min_total:,.2f} "
                    f"exceeds high-value threshold ({ctx.currency} {hv_floor:,.0f}). "
                    f"Requires Head of Strategic Sourcing review."
                ),
                escalate_to="Head of Strategic Sourcing",
                blocking=True,
            ))

        # --- A5: Insufficient quotes for approval threshold -------------------
        if threshold and threshold.quotes_required > len(scored):
            all_esc.append(Escalation(
                rule_id="ER-004",
                trigger=(
                    f"Approval threshold {threshold.rule_id} requires "
                    f"{threshold.quotes_required} quote(s), but only "
                    f"{len(scored)} compliant supplier(s) available."
                ),
                escalate_to="Head of Category",
                blocking=True,
            ))

        # Approval-threshold escalation when required quotes > 1 and single-source conflict
        if threshold and threshold.quotes_required > 1:
            text_lower = ctx.request_text.lower() if ctx.request_text else ""
            single_source_phrases = ["no exception", "only", "exclusively", "no alternative", "sole source"]
            if any(p in text_lower for p in single_source_phrases):
                all_esc.append(Escalation(
                    rule_id=threshold.rule_id,
                    trigger=(
                        f"Approval threshold {threshold.rule_id} requires "
                        f"{threshold.quotes_required} quotes. Request text instruction "
                        f"conflicts with this mandatory requirement. "
                        f"Deviation requires approval from: {threshold.deviation_approval}."
                    ),
                    escalate_to=threshold.deviation_approval or "Procurement Manager",
                    blocking=True,
                ))

    # --- A2: ER-005 (data_residency_constraint_conflict) ----------------------
    if not scored and ctx.data_residency_constraint:
        residency_eliminated = any(
            t.eliminated_at == "policy_compliant"
            and t.reason
            and "data residency" in t.reason.lower()
            for t in eliminated
        )
        if residency_eliminated:
            # Replace the generic ER-004 with ER-005
            all_esc = [
                e for e in all_esc
                if not (e.rule_id == "ER-004" and "no compliant supplier" in e.trigger.lower())
            ]
            all_esc.append(Escalation(
                rule_id="ER-005",
                trigger=(
                    f"Data residency constraint required but no supplier in "
                    f"{ctx.delivery_countries} supports it for "
                    f"{ctx.category_l1}/{ctx.category_l2}. "
                    f"Requires Security and Compliance Review."
                ),
                escalate_to="Security and Compliance Review",
                blocking=True,
            ))

    # --- A4: ER-008 (supplier_not_registered_in_delivery_country) -------------
    if ctx.currency == "USD":
        all_esc.append(Escalation(
            rule_id="ER-008",
            trigger=(
                f"USD-currency request with delivery to {ctx.delivery_countries}. "
                f"Supplier registration and sanction screening in delivery country "
                f"must be verified by Regional Compliance Lead."
            ),
            escalate_to="Regional Compliance Lead",
            blocking=False,
        ))

    return all_esc


def _deduplicate_escalations(escalations: list[Escalation]) -> list[Escalation]:
    """Deduplicate by (rule_id, escalate_to); blocking wins over non-blocking."""
    seen: dict[tuple[str, str], Escalation] = {}
    for esc in escalations:
        key = (esc.rule_id, esc.escalate_to)
        if key not in seen:
            seen[key] = esc
        else:
            # Keep blocking version
            if esc.blocking and not seen[key].blocking:
                seen[key] = esc

    result = list(seen.values())
    # Sort: blocking first, then by rule_id
    result.sort(key=lambda e: (not e.blocking, e.rule_id))
    return result


def _apply_escalation_overrides(escalations: list[Escalation], overrides: dict) -> list[Escalation]:
    """Remove escalations that the user has explicitly overridden/acknowledged."""
    _override_map = {
        "threshold_exceeded": "ER-003",
        "restricted_supplier": "ER-002",
        "single_supplier_risk": "ER-006",
        "data_residency": "ER-005",
        "usd_compliance": "ER-008",
    }
    rules_to_skip = {rule_id for key, rule_id in _override_map.items() if overrides.get(key)}
    if not rules_to_skip:
        return escalations
    return [e for e in escalations if e.rule_id not in rules_to_skip]


def _assign_escalation_ids(escalations: list[Escalation]) -> None:
    for i, esc in enumerate(escalations):
        esc.escalation_id = f"ESC-{i + 1:03d}"


def _format_escalation(e: Escalation) -> dict:
    return {
        "escalation_id": e.escalation_id,
        "rule": e.rule_id,
        "trigger": e.trigger,
        "escalate_to": e.escalate_to,
        "blocking": e.blocking,
    }


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

def _build_recommendation(
    ctx: RequestContext,
    scored: list[ScoredSupplier],
    issues: list[ValidationIssue],
    escalations: list[Escalation],
) -> dict:
    critical = [v for v in issues if v.severity == "critical"]
    blocking_esc = [e for e in escalations if e.blocking]

    if critical or blocking_esc or not scored:
        status = "cannot_proceed"
        reason = _summarise_blocking(critical, blocking_esc, scored)
        top = scored[0] if scored else None
        return {
            "status": status,
            "reason": reason,
            "preferred_supplier_if_resolved": top.supplier_row.supplier_name if top else None,
            "preferred_supplier_rationale": top.trace.escalations[0].trigger if (top and top.trace.escalations) else None,
        }

    high_issues = [v for v in issues if v.severity == "high"]
    non_blocking = [e for e in escalations if not e.blocking]

    if high_issues or non_blocking:
        status = "proceed_with_conditions"
    else:
        status = "proceed"

    top = scored[0]
    return {
        "status": status,
        "reason": (
            f"Recommended supplier: {top.supplier_row.supplier_name} "
            f"(score: {top.composite_score:.3f}, "
            f"total: {ctx.currency} {top.total_price:,.2f})."
            + (f" {len(high_issues) + len(non_blocking)} condition(s) require attention." if status == "proceed_with_conditions" else "")
        ),
        "recommended_supplier_id": top.supplier_row.supplier_id,
        "recommended_supplier_name": top.supplier_row.supplier_name,
    }


def _summarise_blocking(
    critical: list,
    blocking_esc: list[Escalation],
    scored: list[ScoredSupplier],
) -> str:
    parts = []
    for v in critical:
        parts.append(v.description)
    for e in blocking_esc:
        if e.trigger not in " ".join(parts):
            parts.append(e.trigger)
    if not scored:
        parts.append("No compliant suppliers found.")
    return " | ".join(parts[:3]) if parts else "Blocking issues prevent autonomous award."


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------

def _build_policy_evaluation(
    ctx: RequestContext,
    scored: list[ScoredSupplier],
    eliminated: list[SupplierTrace],
    data: DataContext,
) -> dict:
    # Determine contract value for threshold lookup
    if scored:
        min_total = min(s.total_price for s in scored)
    elif ctx.budget_amount:
        min_total = ctx.budget_amount
    else:
        min_total = 0.0

    threshold = find_approval_threshold(data, min_total, ctx.currency)
    threshold_dict: dict = {}
    if threshold:
        threshold_dict = {
            "rule_applied": threshold.rule_id,
            "basis": f"Estimated contract value {ctx.currency} {min_total:,.2f}",
            "quotes_required": threshold.quotes_required,
            "approvers": threshold.approvers,
            "deviation_approval": threshold.deviation_approval,
            "notes": threshold.notes,
        }

    # Preferred supplier status
    pref_dict: dict = {}
    if ctx.preferred_supplier_mentioned:
        pid = ctx.preferred_supplier_id_resolved
        is_preferred = False
        covers_country = False
        is_restricted_flag = False
        pref_note = ""
        discard_reason = ""

        if pid:
            key = (pid, ctx.category_l1, ctx.category_l2)
            pref_entry = data.preferred_index.get(key)
            is_preferred = pref_entry is not None

            # Check if in scored or eliminated
            for s in scored:
                if s.supplier_row.supplier_id == pid:
                    covers_country = True
                    break
            for t in eliminated:
                if t.supplier_id == pid:
                    if t.eliminated_at == "not_restricted":
                        is_restricted_flag = True
                    if t.preference_discarded:
                        discard_reason = t.preference_discard_reason
                    break

        pref_dict = {
            "supplier": ctx.preferred_supplier_mentioned,
            "supplier_id": pid,
            "status": (
                "restricted" if is_restricted_flag
                else "eligible" if not discard_reason
                else f"discarded:{discard_reason}"
            ),
            "is_preferred": is_preferred,
            "covers_delivery_country": covers_country,
            "is_restricted": is_restricted_flag,
            "policy_note": pref_note or (
                "Preferred status confirmed." if is_preferred
                else "Supplier not in preferred suppliers list for this category."
            ),
        }

    # Restricted suppliers relevant to this request
    restricted_relevant: dict = {}
    for entry in data.restricted_suppliers:
        sid = entry.get("supplier_id", "")
        if not sid:
            continue
        cat1 = entry.get("category_l1", "")
        cat2 = entry.get("category_l2", "")
        if cat1 and cat1 != ctx.category_l1:
            continue
        if cat2 and cat2 != ctx.category_l2:
            continue
        rows = data.suppliers_by_id.get(sid, [])
        name = rows[0].supplier_name if rows else sid
        key_str = f"{sid}_{name.replace(' ', '_')}"
        restricted_relevant[key_str] = {
            "restricted": True,
            "restriction_scope": entry.get("restriction_scope") or entry.get("scope", []),
            "reason": entry.get("restriction_reason") or entry.get("reason", ""),
        }

    # Category rules triggered
    category_rules_applied = _collect_triggered_rules(scored, eliminated, "CR-")
    geography_rules_applied = _collect_triggered_rules(scored, eliminated, "GR-")

    result: dict = {
        "approval_threshold": threshold_dict,
        "category_rules_applied": category_rules_applied,
        "geography_rules_applied": geography_rules_applied,
        "restricted_suppliers": restricted_relevant,
    }
    if pref_dict:
        result["preferred_supplier"] = pref_dict
    return result


def _collect_triggered_rules(
    scored: list[ScoredSupplier],
    eliminated: list[SupplierTrace],
    prefix: str,
) -> list[str]:
    seen: set[str] = set()
    for s in scored:
        for esc in s.trace.escalations:
            if esc.rule_id.startswith(prefix):
                seen.add(esc.rule_id)
    for t in eliminated:
        for esc in t.escalations:
            if esc.rule_id.startswith(prefix):
                seen.add(esc.rule_id)
    return sorted(seen)


# ---------------------------------------------------------------------------
# Supplier formatting
# ---------------------------------------------------------------------------

def _format_scored(s: ScoredSupplier, rank: int, fx_info: dict | None = None) -> dict:
    tier = s.pricing_tier
    result = {
        "rank": rank,
        "supplier_id": s.supplier_row.supplier_id,
        "supplier_name": s.supplier_row.supplier_name,
        "preferred": s.is_preferred,
        "incumbent": s.is_incumbent,
        "pricing_tier_applied": f"{tier.min_quantity:g}–{tier.max_quantity:g} units",
        "unit_price_eur": s.unit_price,
        "total_price_eur": round(s.total_price, 2),
        "currency": tier.currency,
        "standard_lead_time_days": tier.standard_lead_time_days,
        "expedited_lead_time_days": tier.expedited_lead_time_days,
        "expedited_unit_price_eur": tier.expedited_unit_price,
        "expedited_total_eur": round(s.expedited_total_price, 2),
        "using_expedited_pricing": s.using_expedited,
        "effective_lead_time_days": s.effective_lead_time,
        "quality_score": s.supplier_row.quality_score,
        "risk_score": s.supplier_row.risk_score,
        "esg_score": s.supplier_row.esg_score,
        "data_residency_supported": s.supplier_row.data_residency_supported,
        "policy_compliant": True,
        "covers_delivery_country": True,
        "composite_score": s.composite_score,
        "score_breakdown": s.score_breakdown,
        "fit_rationale": s.fit_rationale,
        "recommendation_note": _recommendation_note(s),
    }
    # Add indicative FX-converted total when currencies differ
    if fx_info and tier.currency != fx_info["request_currency"]:
        converted, rate, source = fx_convert(
            s.total_price, tier.currency, fx_info["request_currency"]
        )
        result["total_price_request_currency_indicative"] = converted
        result["fx_rate"] = rate
        result["fx_rate_source"] = source
        result["fx_disclaimer"] = (
            "Indicative only. Converted values require confirmation "
            "before use in procurement decisions."
        )
    return result


def _format_scored_excluded(s: ScoredSupplier) -> dict:
    return {
        "supplier_id": s.supplier_row.supplier_id,
        "supplier_name": s.supplier_row.supplier_name,
        "reason": f"Ranked outside top {config.SHORTLIST_MAX} (score: {s.composite_score:.3f})",
        "stages_passed": s.trace.stages_passed,
    }


def _format_eliminated(t: SupplierTrace) -> dict:
    return {
        "supplier_id": t.supplier_id,
        "supplier_name": t.supplier_name,
        "eliminated_at": t.eliminated_at,
        "reason": t.reason,
        "stages_passed": t.stages_passed,
    }


def _recommendation_note(s: ScoredSupplier) -> str:
    parts: list[str] = []
    if s.is_preferred:
        parts.append("Preferred supplier.")
    if s.is_incumbent:
        parts.append("Incumbent supplier.")
    if s.using_expedited:
        parts.append(f"Expedited pricing applied (lead time {s.effective_lead_time}d).")
    if s.fit_rationale:
        parts.append(s.fit_rationale)
    return " ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def _build_audit_trail(
    ctx: RequestContext,
    scored: list[ScoredSupplier],
    eliminated: list[SupplierTrace],
    data: DataContext,
    issues: list[ValidationIssue],
    escalations: list[Escalation],
) -> dict:
    policies_checked: set[str] = set()
    for e in escalations:
        policies_checked.add(e.rule_id)
    for v in issues:
        if v.issue_type == "budget_insufficient":
            policies_checked.add("AT-xxx")  # threshold rules
    # Add category/geo rules
    for s in scored:
        for esc in s.trace.escalations:
            policies_checked.add(esc.rule_id)
    for t in eliminated:
        for esc in t.escalations:
            policies_checked.add(esc.rule_id)

    supplier_ids = list({s.supplier_row.supplier_id for s in scored} | {t.supplier_id for t in eliminated})

    # Pricing tiers applied
    tiers_applied = sorted({
        f"{s.pricing_tier.min_quantity:g}–{s.pricing_tier.max_quantity:g} "
        f"({s.pricing_tier.region}, {s.pricing_tier.currency})"
        for s in scored
    })

    historical = data.historical_by_request.get(ctx.request_id, [])

    return {
        "policies_checked": sorted(policies_checked),
        "supplier_ids_evaluated": sorted(supplier_ids),
        "pricing_tiers_applied": tiers_applied,
        "data_sources_used": ["requests.json", "suppliers.csv", "pricing.csv", "policies.json"],
        "historical_awards_consulted": bool(historical),
        "historical_award_note": (
            f"{len(historical)} historical award(s) found for {ctx.request_id}. "
            "Used for context only."
            if historical else "No historical awards found for this request."
        ),
    }


# ---------------------------------------------------------------------------
# Uncertainties
# ---------------------------------------------------------------------------

def _detect_uncertainties(
    ctx: RequestContext,
    scored: list[ScoredSupplier],
    eliminated: list[SupplierTrace],
    data: DataContext,
) -> list[Uncertainty]:
    uncertainties: list[Uncertainty] = []

    # 1. Missing required_by_date
    if ctx.required_by_date is None:
        uncertainties.append(Uncertainty(
            uncertainty_type="missing_field",
            source="required_by_date",
            description="Required-by date is not specified.",
            assumption_made="No deadline constraint assumed.",
            impact="Lead-time scoring disabled; suppliers not filtered by delivery speed.",
        ))

    # 2. Missing budget_amount
    if ctx.budget_amount is None:
        uncertainties.append(Uncertainty(
            uncertainty_type="missing_field",
            source="budget_amount",
            description="Budget amount is not specified.",
            assumption_made="Approval tier based on lowest supplier price.",
            impact="Budget sufficiency cannot be validated; approval threshold may be inaccurate.",
        ))

    # 3. Missing quantity
    if ctx.quantity is None:
        uncertainties.append(Uncertainty(
            uncertainty_type="missing_field",
            source="quantity",
            description="Quantity field is null.",
            assumption_made="Quantity=1 used for pricing lookup.",
            impact="Pricing tier may not reflect actual volume; MOQ check skipped.",
        ))

    # 4. LLM decomposition failed
    if not ctx.llm_parse_success:
        uncertainties.append(Uncertainty(
            uncertainty_type="degraded_analysis",
            source="llm_decomposition",
            description="LLM-based requirement decomposition did not succeed.",
            assumption_made="Scoring based on structured fields only.",
            impact="Free-text requirements, subjective criteria not applied.",
        ))

    # 5. Currency conversion (cross-currency)
    if scored:
        supplier_currencies = {s.pricing_tier.currency for s in scored}
        mismatched = supplier_currencies - {ctx.currency}
        if mismatched:
            _, rate, source = fx_convert(1.0, list(mismatched)[0], ctx.currency)
            uncertainties.append(Uncertainty(
                uncertainty_type="assumption",
                source="currency_conversion",
                description=(
                    f"Request currency ({ctx.currency}) differs from supplier pricing "
                    f"currency ({', '.join(sorted(mismatched))}). Indicative conversion applied."
                ),
                assumption_made=(
                    f"FX rate from {source}. This is for display purposes only."
                ),
                impact=(
                    "All converted values are indicative. Budget sufficiency and "
                    "approval tier determined using original currencies only."
                ),
                requires_approval=True,
            ))

    # 6. Quantity discrepancy
    if ctx.quantity_discrepancy and ctx.quantity is not None and ctx.quantity_in_text is not None:
        uncertainties.append(Uncertainty(
            uncertainty_type="assumption",
            source="quantity_field",
            description=(
                f"Quantity field ({ctx.quantity:g}) differs from text-mentioned "
                f"quantity ({ctx.quantity_in_text:g})."
            ),
            assumption_made=f"Used field value ({ctx.quantity:g}) over text value ({ctx.quantity_in_text:g}).",
            impact="If text quantity is correct, pricing tier and total cost may differ.",
        ))

    # 7. Preferred supplier fuzzy match
    if ctx.preferred_supplier_fuzzy_match and ctx.preferred_supplier_mentioned:
        uncertainties.append(Uncertainty(
            uncertainty_type="ambiguity",
            source="preferred_supplier",
            description=(
                f"Preferred supplier '{ctx.preferred_supplier_mentioned}' resolved "
                f"to {ctx.preferred_supplier_id_resolved} via substring match."
            ),
            assumption_made=(
                f"Resolved '{ctx.preferred_supplier_mentioned}' to "
                f"{ctx.preferred_supplier_id_resolved} via substring."
            ),
            impact="If resolution is wrong, preference boost may apply to wrong supplier.",
        ))

    # 8. No historical awards
    historical = data.historical_by_request.get(ctx.request_id, [])
    if not historical:
        uncertainties.append(Uncertainty(
            uncertainty_type="missing_field",
            source="historical_awards",
            description=f"No historical awards found for {ctx.request_id}.",
            assumption_made="Ranking based on current data only.",
            impact="No precedent context available.",
        ))

    return uncertainties


# ---------------------------------------------------------------------------
# FX conversion helpers
# ---------------------------------------------------------------------------

def _compute_fx_info(
    ctx: RequestContext,
    scored: list[ScoredSupplier],
) -> dict | None:
    """If any supplier currency differs from request currency, compute FX info."""
    if not scored:
        return None

    supplier_currencies = {s.pricing_tier.currency for s in scored}
    mismatched = supplier_currencies - {ctx.currency}
    if not mismatched:
        return None

    # Convert budget if available
    interpretation_extra: dict = {}
    if ctx.budget_amount is not None:
        # Pick the first mismatched currency for display
        other = sorted(mismatched)[0]
        converted, rate, source = fx_convert(ctx.budget_amount, ctx.currency, other)
        interpretation_extra = {
            "budget_amount_indicative_converted": converted,
            "budget_converted_currency": other,
            "fx_rate_used": rate,
            "fx_rate_source": source,
            "fx_disclaimer": (
                "Indicative only. Converted values require confirmation "
                "before use in procurement decisions."
            ),
        }

    return {
        "request_currency": ctx.currency,
        "interpretation_extra": interpretation_extra,
    }
