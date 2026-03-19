"""
All tunables for the ChainIQ supplier ranking pipeline.
Change values here — never hardcode them inline.
"""

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 1.0 when all active)
# ESG weight is only active when esg_requirement=True
# Lead time weight is only active when days_until_required is not None
# Fit weight is added (and others renormalized) when subjective_criteria non-empty
# ---------------------------------------------------------------------------
SCORING_WEIGHTS: dict[str, float] = {
    "price":     0.35,
    "quality":   0.25,
    "risk":      0.20,
    "esg":       0.10,
    "lead_time": 0.10,
}

# Weight added for LLM fit score when subjective criteria are present
FIT_WEIGHT: float = 0.10

# ---------------------------------------------------------------------------
# Supplier boosts (applied after composite score, score capped at 1.0)
# ---------------------------------------------------------------------------
BOOST_PREFERRED: float = 0.05
BOOST_INCUMBENT: float = 0.03

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
SHORTLIST_MAX: int = 5

# Use expedited lead time / pricing when days_until_required <= this threshold
EXPEDITED_DAYS_THRESHOLD: int = 14

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
LLM_ENABLED: bool = True
LLM_TIMEOUT_SECONDS: int = 10
LLM_MODEL: str = "llama-3.3-70b-versatile"
LLM_TEMPERATURE: float = 0.0

# ---------------------------------------------------------------------------
# Value-conditional supplier restrictions
# The threshold is buried in policies.json restriction_reason as free text,
# so it is hardcoded here to avoid fragile NLP parsing.
# Key: supplier_id → category_l2 → {currency, threshold}
# ---------------------------------------------------------------------------
CONDITIONAL_RESTRICTION_THRESHOLDS: dict[str, dict[str, dict]] = {
    "SUP-0045": {
        "Influencer Campaign Management": {
            "currency": "EUR",
            "threshold": 75_000.0,
        }
    }
}

# ---------------------------------------------------------------------------
# Budget feasibility: allow a small tolerance above stated budget before
# flagging as "budget_insufficient" (e.g. rounding artefacts)
# ---------------------------------------------------------------------------
BUDGET_TOLERANCE_FRACTION: float = 0.001   # 0.1%

# ---------------------------------------------------------------------------
# Quantity discrepancy threshold: flag if text quantity differs from field
# by more than this fraction of the field value
# ---------------------------------------------------------------------------
QUANTITY_DISCREPANCY_THRESHOLD: float = 0.05   # 5%
