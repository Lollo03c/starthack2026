"""
Phase 2: Scoring and Ranking.

For each supplier that passed Phase 1:
  1. Determine effective pricing (standard vs expedited)
  2. Compute per-component scores (normalised 0–1 across the candidate set)
  3. Redistribute weights for inactive components
  4. Compute composite score
  5. Apply preferred / incumbent boosts
  6. Optionally call LLM fit scoring for subjective criteria
  7. Rank by composite score descending
"""
from __future__ import annotations

import logging
from datetime import date

from engine import config
from engine.data_loader import find_pricing_tier
from engine.types import (
    DataContext,
    RequestContext,
    ScoredSupplier,
    SupplierRow,
    SupplierTrace,
)

logger = logging.getLogger(__name__)


def score_and_rank(
    passed: list[SupplierTrace],
    ctx: RequestContext,
    data: DataContext,
) -> list[ScoredSupplier]:
    """Score and rank all suppliers that passed Phase 1.

    Returns list sorted by composite_score descending (best first).
    """
    if not passed:
        return []

    candidates = _build_candidates(passed, ctx, data)
    if not candidates:
        return []

    _add_llm_fit_scores(candidates, ctx)
    _compute_composite_scores(candidates, ctx, data)
    candidates.sort(key=lambda c: c.composite_score, reverse=True)
    _promote_mandated_supplier(candidates, ctx)
    return candidates


# ---------------------------------------------------------------------------
# Step 1: Build initial candidate list with pricing
# ---------------------------------------------------------------------------

def _build_candidates(
    passed: list[SupplierTrace],
    ctx: RequestContext,
    data: DataContext,
) -> list[ScoredSupplier]:
    candidates: list[ScoredSupplier] = []
    delivery_country = ctx.delivery_countries[0] if ctx.delivery_countries else "DE"
    quantity = ctx.quantity if ctx.quantity is not None else 1.0
    ref_date = date.today()

    use_expedited = (
        ctx.days_until_required is not None
        and ctx.days_until_required <= config.EXPEDITED_DAYS_THRESHOLD
    )

    for trace in passed:
        supplier_rows = data.suppliers_by_id.get(trace.supplier_id, [])
        supplier_row = next(
            (
                r for r in supplier_rows
                if r.category_l1 == ctx.category_l1 and r.category_l2 == ctx.category_l2
            ),
            None,
        )
        if supplier_row is None:
            continue

        # Use cached tier from Phase 1 if available; otherwise re-lookup
        tier = trace.pricing_tier
        if tier is None:
            tier = find_pricing_tier(
                data,
                trace.supplier_id,
                ctx.category_l1,
                ctx.category_l2,
                delivery_country,
                quantity,
                ref_date,
            )
        if tier is None:
            logger.warning("No pricing tier found for %s in Phase 2; skipping.", trace.supplier_id)
            continue

        unit_price = tier.expedited_unit_price if use_expedited else tier.unit_price
        total_price = unit_price * quantity

        is_preferred = _is_preferred(supplier_row, ctx, data, trace)
        is_incumbent = _is_incumbent(supplier_row, ctx)

        candidates.append(ScoredSupplier(
            supplier_row=supplier_row,
            trace=trace,
            pricing_tier=tier,
            unit_price=unit_price,
            total_price=total_price,
            expedited_unit_price=tier.expedited_unit_price,
            expedited_total_price=tier.expedited_unit_price * quantity,
            effective_lead_time=(
                tier.expedited_lead_time_days if use_expedited
                else tier.standard_lead_time_days
            ),
            using_expedited=use_expedited,
            composite_score=0.0,
            score_breakdown={},
            is_preferred=is_preferred,
            is_incumbent=is_incumbent,
        ))

    return candidates


# ---------------------------------------------------------------------------
# Step 2: LLM fit scores (only if subjective criteria present)
# ---------------------------------------------------------------------------

def _add_llm_fit_scores(candidates: list[ScoredSupplier], ctx: RequestContext) -> None:
    if not ctx.subjective_criteria or not config.LLM_ENABLED:
        return

    from engine.llm_client import llm_fit_score

    for c in candidates:
        profile = {
            "supplier_name": c.supplier_row.supplier_name,
            "category_l2": c.supplier_row.category_l2,
            "quality_score": c.supplier_row.quality_score,
            "risk_score": c.supplier_row.risk_score,
            "esg_score": c.supplier_row.esg_score,
            "pricing_model": c.supplier_row.pricing_model,
            "data_residency_supported": c.supplier_row.data_residency_supported,
            "contract_status": c.supplier_row.contract_status,
        }
        result = llm_fit_score(profile, ctx.subjective_criteria)
        c.score_breakdown["fit"] = result.score
        c.fit_rationale = result.rationale
        if not result.success:
            c.trace.escalations  # just referencing; no change needed


# ---------------------------------------------------------------------------
# Step 3: Composite score computation
# ---------------------------------------------------------------------------

def _compute_composite_scores(
    candidates: list[ScoredSupplier],
    ctx: RequestContext,
    data: DataContext,
) -> None:
    if not candidates:
        return

    # Collect raw values for normalisation
    prices       = [c.total_price              for c in candidates]
    qualities    = [c.supplier_row.quality_score for c in candidates]
    risks        = [c.supplier_row.risk_score    for c in candidates]
    esgs         = [c.supplier_row.esg_score     for c in candidates]
    lead_times   = [c.effective_lead_time        for c in candidates]

    for c in candidates:
        breakdown: dict[str, float] = {}

        # Price (inverted: lower is better)
        breakdown["price"] = _norm_inverted(c.total_price, prices)

        # Quality (higher is better, already 0–100)
        breakdown["quality"] = _norm(c.supplier_row.quality_score, qualities)

        # Risk (inverted: lower is better)
        breakdown["risk"] = _norm_inverted(c.supplier_row.risk_score, risks)

        # ESG
        breakdown["esg"] = _norm(c.supplier_row.esg_score, esgs)

        # Lead time (inverted: lower is better)
        breakdown["lead_time"] = _norm_inverted(c.effective_lead_time, lead_times)

        # Fit (from LLM or default 0.5)
        if ctx.subjective_criteria:
            breakdown["fit"] = c.score_breakdown.get("fit", 0.5)

        # Active weights
        active_weights = dict(config.SCORING_WEIGHTS)
        if not ctx.esg_requirement:
            del active_weights["esg"]
        if ctx.days_until_required is None:
            del active_weights["lead_time"]
        if ctx.subjective_criteria:
            active_weights["fit"] = config.FIT_WEIGHT

        # Normalise weights to sum to 1.0
        total_w = sum(active_weights.values())
        norm_weights = {k: v / total_w for k, v in active_weights.items()}

        # Composite score
        score = sum(
            norm_weights.get(component, 0.0) * value
            for component, value in breakdown.items()
        )

        # Boosts (applied after composite, capped at 1.0)
        if c.is_preferred:
            score += config.BOOST_PREFERRED
        if c.is_incumbent:
            score += config.BOOST_INCUMBENT
        score = min(score, 1.0)

        c.composite_score = round(score, 6)
        c.score_breakdown = {k: round(v, 4) for k, v in breakdown.items()}


def _promote_mandated_supplier(
    candidates: list[ScoredSupplier],
    ctx: RequestContext,
) -> None:
    """Keep the mandatory supplier as the default choice while preserving alternatives."""
    if not ctx.supplier_must_use or not ctx.preferred_supplier_id_resolved or not candidates:
        return

    mandated_idx = next(
        (idx for idx, candidate in enumerate(candidates)
         if candidate.supplier_row.supplier_id == ctx.preferred_supplier_id_resolved),
        None,
    )
    if mandated_idx is None or mandated_idx == 0:
        return

    mandated = candidates.pop(mandated_idx)
    candidates.insert(0, mandated)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _norm(value: float, values: list[float]) -> float:
    """Normalise a value to [0, 1]; higher raw value → higher score."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return 1.0
    return (value - lo) / (hi - lo)


def _norm_inverted(value: float, values: list[float]) -> float:
    """Normalise a value to [0, 1]; lower raw value → higher score."""
    lo, hi = min(values), max(values)
    if hi == lo:
        return 1.0
    return 1.0 - (value - lo) / (hi - lo)


# ---------------------------------------------------------------------------
# Preference and incumbency checks
# ---------------------------------------------------------------------------

def _is_preferred(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
    trace: SupplierTrace,
) -> bool:
    """True if this supplier is a preferred supplier for this category/region."""
    if trace.preference_discarded:
        return False
    key = (supplier.supplier_id, ctx.category_l1, ctx.category_l2)
    entry = data.preferred_index.get(key)
    if entry is None:
        return False

    # Check region scope if present
    region_scope = entry.get("region_scope")
    if region_scope:
        from engine.geo_utils import country_to_region
        request_regions = {country_to_region(c) for c in ctx.delivery_countries}
        if not (request_regions & set(region_scope)):
            return False

    return True


def _is_incumbent(supplier: SupplierRow, ctx: RequestContext) -> bool:
    """True if this supplier matches the incumbent supplier on the request."""
    if not ctx.incumbent_supplier_id_resolved:
        # Fall back to name comparison
        if ctx.incumbent_supplier:
            return ctx.incumbent_supplier.lower() in supplier.supplier_name.lower()
        return False
    return supplier.supplier_id == ctx.incumbent_supplier_id_resolved
