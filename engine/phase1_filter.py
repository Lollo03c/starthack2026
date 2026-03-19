"""
Phase 1: Deterministic Filter Pipeline.

Runs each supplier through CHECK_PIPELINE with early exit on first failure.
Suppliers are processed independently; their traces and escalations are
collected for the output builder.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from engine.checks import CHECK_PIPELINE
from engine.types import DataContext, Escalation, RequestContext, SupplierRow, SupplierTrace

logger = logging.getLogger(__name__)


def run_filter_pipeline(
    candidates: list[SupplierRow],
    ctx: RequestContext,
    data: DataContext,
) -> tuple[list[SupplierTrace], list[SupplierTrace]]:
    """Run all candidates through the check pipeline.

    Returns:
        passed:    list of SupplierTrace for suppliers that passed all checks
        eliminated: list of SupplierTrace for suppliers that failed at least one check

    The order of passed/eliminated lists preserves the order of candidates.
    """
    if not candidates:
        return [], []

    # Process suppliers (parallel across suppliers, sequential within each)
    results: dict[int, tuple[SupplierTrace, bool]] = {}
    with ThreadPoolExecutor(max_workers=min(len(candidates), 8)) as executor:
        futures = {
            executor.submit(_run_single, supplier, ctx, data): idx
            for idx, supplier in enumerate(candidates)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                logger.error(
                    "Unexpected error processing supplier %s: %s",
                    candidates[idx].supplier_id,
                    exc,
                )
                # Safety fallback: create a failed trace
                supplier = candidates[idx]
                trace = SupplierTrace(
                    supplier_id=supplier.supplier_id,
                    supplier_name=supplier.supplier_name,
                    eliminated_at="internal_error",
                    reason=f"Internal error: {exc}",
                )
                results[idx] = (trace, False)

    passed: list[SupplierTrace] = []
    eliminated: list[SupplierTrace] = []

    for idx in sorted(results):
        trace, did_pass = results[idx]
        if did_pass:
            passed.append(trace)
        else:
            eliminated.append(trace)

    return passed, eliminated


def _run_single(
    supplier: SupplierRow,
    ctx: RequestContext,
    data: DataContext,
) -> tuple[SupplierTrace, bool]:
    """Run one supplier through every check stage. Returns (trace, passed)."""
    trace = SupplierTrace(
        supplier_id=supplier.supplier_id,
        supplier_name=supplier.supplier_name,
    )

    for stage_name, check_fn in CHECK_PIPELINE:
        result = check_fn(supplier, ctx, data)
        trace.escalations.extend(result.escalations)

        if result.passed:
            trace.stages_passed.append(stage_name)

            # Special handling for pricing_available: cache the found tier
            if stage_name == "pricing_available":
                tier = getattr(result, "_pricing_tier", None)
                if tier is not None:
                    trace.pricing_tier = tier

            # Special handling for preferred_validation: detect discarded preference
            if stage_name == "preferred_validation" and result.reason:
                if result.reason.startswith("PREFERENCE_DISCARDED:"):
                    trace.preference_discarded = True
                    trace.preference_discard_reason = result.reason.split(":", 1)[1]

        else:
            trace.eliminated_at = stage_name
            trace.reason = result.reason
            return trace, False

    return trace, True


def collect_all_escalations(
    passed: list[SupplierTrace],
    eliminated: list[SupplierTrace],
) -> list[Escalation]:
    """Collect escalations from all traces (both passed and eliminated)."""
    all_esc: list[Escalation] = []
    for trace in passed + eliminated:
        all_esc.extend(trace.escalations)
    return all_esc
