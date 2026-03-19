"""
ChainIQ Supplier Ranking Pipeline — Public API.

Usage:
    from engine import load_data, process_request

    data = load_data("data/")           # once at startup
    output = process_request(req, data) # per request
"""
from __future__ import annotations

from dataclasses import replace

from engine.data_loader import load_data
from engine.types import DataContext

__all__ = ["load_data", "process_request"]


def process_request(request_dict: dict, data: DataContext) -> dict:
    """Run the full 3-phase pipeline for a single purchase request.

    Args:
        request_dict: The raw request JSON as a Python dict.
        data:         DataContext loaded via load_data().

    Returns:
        Output JSON as a Python dict matching the example_output.json schema.
    """
    from engine.output_builder import build_output
    from engine.phase0_parse import parse_request
    from engine.phase1_filter import run_filter_pipeline
    from engine.phase2_score import score_and_rank

    # Phase 0: parse request into RequestContext
    ctx = parse_request(request_dict, data)

    # Get candidate suppliers for this category
    candidates = data.suppliers_by_category.get(
        (ctx.category_l1, ctx.category_l2), []
    )

    # Phase 1: deterministic filter pipeline
    passed, eliminated = run_filter_pipeline(candidates, ctx, data)

    # If the user mandated a supplier but that path yields no supplier,
    # build an alternative shortlist without silently dropping the mandate.
    if ctx.supplier_must_use and not passed:
        relaxed_ctx = replace(ctx, supplier_must_use=False, mandated_supplier_fallback_used=True)
        alt_passed, alt_eliminated = run_filter_pipeline(candidates, relaxed_ctx, data)
        if alt_passed:
            ctx.mandated_supplier_fallback_used = True
            passed, eliminated = alt_passed, alt_eliminated

    # Phase 2: scoring and ranking
    scored = score_and_rank(passed, ctx, data)

    # Assemble output JSON
    return build_output(request_dict, ctx, scored, eliminated, data)
