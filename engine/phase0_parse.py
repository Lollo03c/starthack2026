"""
Phase 0: Request Parsing.

Converts a raw request dict into a RequestContext with:
  1. Deterministic field extraction (no LLM, never fails)
  2. Supplier name resolution (preferred / incumbent)
  3. Optional LLM-assisted constraint decomposition
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

from engine import config
from engine.types import DataContext, RequestContext

logger = logging.getLogger(__name__)


def parse_request(request_dict: dict, data: DataContext) -> RequestContext:
    """Convert a raw request dict to a RequestContext.

    Steps:
    1. Copy structured fields
    2. Compute days_until_required
    3. Resolve preferred / incumbent supplier names → IDs
    4. LLM decomposition of request_text (if LLM_ENABLED)
    """
    d = request_dict

    # --- Basic fields ---------------------------------------------------------
    required_by_date = _parse_date(d.get("required_by_date"))
    today = date.today()
    days_until_required: int | None = None
    if required_by_date is not None:
        days_until_required = (required_by_date - today).days

    delivery_countries: list[str] = d.get("delivery_countries") or []
    if isinstance(delivery_countries, str):
        delivery_countries = [delivery_countries]

    ctx = RequestContext(
        request_id=str(d.get("request_id", "")),
        created_at=str(d.get("created_at", "")),
        request_channel=str(d.get("request_channel", "")),
        request_language=str(d.get("request_language") or d.get("language") or "en"),
        business_unit=str(d.get("business_unit", "")),
        country=str(d.get("country", "")),
        site=str(d.get("site", "")),
        requester_id=str(d.get("requester_id", "")),
        requester_role=str(d.get("requester_role", "")),
        submitted_for_id=str(d.get("submitted_for_id", "")),
        category_l1=str(d.get("category_l1", "")),
        category_l2=str(d.get("category_l2", "")),
        title=str(d.get("title", "")),
        request_text=str(d.get("request_text", "")),
        currency=str(d.get("currency", "EUR")),
        budget_amount=_float_or_none(d.get("budget_amount")),
        quantity=_float_or_none(d.get("quantity")),
        unit_of_measure=str(d.get("unit_of_measure", "unit")),
        required_by_date=required_by_date,
        preferred_supplier_mentioned=_str_or_none(d.get("preferred_supplier_mentioned")),
        supplier_must_use=_bool_or_false(d.get("supplier_must_use")),
        incumbent_supplier=_str_or_none(d.get("incumbent_supplier")),
        delivery_countries=delivery_countries,
        data_residency_constraint=bool(d.get("data_residency_constraint", False)),
        esg_requirement=bool(d.get("esg_requirement", False)),
        days_until_required=days_until_required,
    )

    # --- Resolve supplier names to IDs ----------------------------------------
    ctx.preferred_supplier_id_resolved, ctx.preferred_supplier_fuzzy_match = (
        _resolve_supplier_name(ctx.preferred_supplier_mentioned, data)
    )
    ctx.incumbent_supplier_id_resolved, _ = _resolve_supplier_name(
        ctx.incumbent_supplier, data
    )

    if (
        ctx.preferred_supplier_mentioned
        and not ctx.supplier_must_use
    ):
        ctx.supplier_must_use = _infer_must_use_supplier(
            ctx.request_text,
            ctx.preferred_supplier_mentioned,
        )

    # --- LLM decomposition (optional) -----------------------------------------
    if config.LLM_ENABLED and ctx.request_text:
        _run_llm_decomposition(ctx)

    return ctx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_llm_decomposition(ctx: RequestContext) -> None:
    """Populate LLM-derived fields on ctx in place. Never raises."""
    from engine.llm_client import llm_decompose

    result = llm_decompose(
        request_text=ctx.request_text,
        language=ctx.request_language,
        category_l1=ctx.category_l1,
        category_l2=ctx.category_l2,
    )
    if not result.success:
        return

    ctx.structured_checks = result.structured_checks
    ctx.unknown_checks = result.unknown_checks
    ctx.subjective_criteria = result.subjective_criteria
    ctx.llm_detected_language = result.detected_language
    ctx.llm_parse_success = True

    # Quantity discrepancy check
    if (
        result.quantity_in_text is not None
        and ctx.quantity is not None
        and ctx.quantity > 0
    ):
        diff_fraction = abs(result.quantity_in_text - ctx.quantity) / ctx.quantity
        if diff_fraction > config.QUANTITY_DISCREPANCY_THRESHOLD:
            ctx.quantity_discrepancy = True
            ctx.quantity_in_text = result.quantity_in_text


def _resolve_supplier_name(
    name: str | None, data: DataContext
) -> tuple[str | None, bool]:
    """Attempt to resolve a supplier display name to a supplier_id.

    Tries exact match first, then case-insensitive, then substring.
    Returns (supplier_id or None, fuzzy_match: bool).
    """
    if not name:
        return None, False
    name_lower = name.lower().strip()

    # Collect all unique (supplier_id, supplier_name) pairs
    seen: dict[str, str] = {}  # supplier_id → supplier_name
    for rows in data.suppliers_by_id.values():
        for row in rows:
            seen[row.supplier_id] = row.supplier_name

    # Exact match
    for sid, sname in seen.items():
        if sname == name.strip():
            return sid, False

    # Case-insensitive exact
    for sid, sname in seen.items():
        if sname.lower() == name_lower:
            return sid, False

    # Substring (name contains supplier name or vice versa)
    for sid, sname in seen.items():
        if name_lower in sname.lower() or sname.lower() in name_lower:
            logger.info("Fuzzy-matched supplier '%s' → %s (%s)", name, sid, sname)
            return sid, True

    logger.debug("Could not resolve supplier name '%s' to a supplier_id", name)
    return None, False


def _parse_date(value) -> date | None:
    if value is None:
        return None
    try:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _bool_or_false(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return False


def _infer_must_use_supplier(request_text: str, supplier_name: str | None = None) -> bool:
    if not request_text:
        return False
    text = request_text.lower()
    hard_patterns = [
        r"\bonly\b",
        r"\bexclusive(?:ly)?\b",
        r"\bmust use\b",
        r"\bno other provider",
        r"\bno other providers",
        r"\bno alternative",
        r"\bsole source\b",
        r"\bmandatory supplier\b",
        r"\bdo not use any other supplier\b",
        r"\bfrom [a-z0-9 .&'-]+ only\b",
    ]
    if any(re.search(pattern, text) for pattern in hard_patterns):
        return True
    if supplier_name:
        supplier_lower = supplier_name.lower().strip()
        supplier_pattern = re.escape(supplier_lower)
        supplier_specific_patterns = [
            rf"\bmust\b.{{0,80}}\bfrom\s+{supplier_pattern}\b",
            rf"\bonly\s+{supplier_pattern}\b",
            rf"\b{supplier_pattern}\s+only\b",
            rf"\bmust use\s+{supplier_pattern}\b",
        ]
        if any(re.search(pattern, text) for pattern in supplier_specific_patterns):
            return True
    return False
