"""
Thin wrapper around the Groq API for LLM-assisted request parsing and
supplier fit scoring.

Both public functions degrade gracefully: any exception returns a fallback
result so the pipeline always produces valid output even when the LLM is
unavailable.

Usage:
    from engine.llm_client import llm_decompose, llm_fit_score
"""
from __future__ import annotations

import json
import logging
import os

from engine import config
from engine.types import (
    DecompositionResult,
    FitScoreResult,
    StructuredCheck,
    SubjectiveCriterion,
    UnknownCheck,
)

from dotenv import load_dotenv
load_dotenv()  # load starthack2026/.env automatically


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Groq client (lazy-initialised so import never raises)
# ---------------------------------------------------------------------------

_groq_client = None


def _get_client():
    global _groq_client
    if _groq_client is None:
        try:
            from groq import Groq  # type: ignore
            api_key = os.environ.get("GROQ_API_KEY", "")
            _groq_client = Groq(api_key=api_key)
        except Exception as exc:
            logger.warning("Could not initialise Groq client: %s", exc)
    return _groq_client


def _call_llm(messages: list[dict], *, timeout: int | None = None) -> str | None:
    """Make a single Groq API call. Returns the content string or None on failure."""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
            temperature=config.LLM_TEMPERATURE,
            response_format={"type": "json_object"},
            timeout=timeout or config.LLM_TIMEOUT_SECONDS,
        )
        return resp.choices[0].message.content
    except Exception as exc:
        logger.warning("Groq API call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Phase 0: Constraint decomposition
# ---------------------------------------------------------------------------

_DECOMPOSE_SYSTEM = """You are a procurement analyst. Extract structured information from a purchase request text.
Respond ONLY with a JSON object in exactly this schema — no extra keys, no markdown:

{
  "structured_checks": [
    {"check": "<check_name>", "value": "<value>", "operator": "eq|gte|lte|contains"}
  ],
  "unknown_checks": [
    {
      "check": "<short_label>",
      "description": "<full verifiable description>",
      "field_path": "<supplier_field_or_empty>",
      "operator": "<eq|gte|lte|contains|exists|empty>",
      "value": "<value_or_null>"
    }
  ],
  "subjective_criteria": [
    {"criterion": "<description>", "importance": "must_have|nice_to_have"}
  ],
  "quantity_in_text": <number_or_null>,
  "detected_language": "<iso_639_1_code>"
}

Rules:
- structured_checks: only for things that map to known supplier data fields
  (e.g. capability, certification, data_residency_supported, contract_status)
- unknown_checks: verifiable claims not in supplier data (e.g. "must be ISO 27001 certified")
- subjective_criteria: opinions, preferences, style guidance that cannot be verified objectively
- quantity_in_text: numeric quantity mentioned in the text (NOT the structured quantity field)
- detected_language: ISO 639-1 code of the request language
- If a bucket is empty, return an empty array []
- Do NOT add duplicate entries across buckets
"""


def llm_decompose(
    request_text: str,
    language: str,
    category_l1: str,
    category_l2: str,
) -> DecompositionResult:
    """Parse request_text into structured/unknown checks and subjective criteria.

    Falls back to an empty DecompositionResult on any failure.
    """
    if not request_text or not config.LLM_ENABLED:
        return DecompositionResult(success=False)

    user_msg = (
        f"Language hint: {language}\n"
        f"Category: {category_l1} / {category_l2}\n\n"
        f"Request text:\n{request_text}"
    )

    raw = _call_llm([
        {"role": "system", "content": _DECOMPOSE_SYSTEM},
        {"role": "user", "content": user_msg},
    ])
    if raw is None:
        return DecompositionResult(success=False)

    try:
        data = json.loads(raw)
        structured = [
            StructuredCheck(
                check=c.get("check", ""),
                value=c.get("value"),
                operator=c.get("operator", "eq"),
            )
            for c in data.get("structured_checks", [])
        ]
        unknown = [
            UnknownCheck(
                check=c.get("check", ""),
                description=c.get("description", ""),
                field_path=c.get("field_path", ""),
                operator=c.get("operator", ""),
                value=c.get("value"),
            )
            for c in data.get("unknown_checks", [])
        ]
        subjective = [
            SubjectiveCriterion(
                criterion=c.get("criterion", ""),
                importance=c.get("importance", "nice_to_have"),
            )
            for c in data.get("subjective_criteria", [])
        ]
        qty = data.get("quantity_in_text")
        lang = data.get("detected_language", language)

        return DecompositionResult(
            success=True,
            structured_checks=structured,
            unknown_checks=unknown,
            subjective_criteria=subjective,
            quantity_in_text=float(qty) if qty is not None else None,
            detected_language=lang,
        )
    except Exception as exc:
        logger.warning("Failed to parse LLM decomposition response: %s", exc)
        return DecompositionResult(success=False)


# ---------------------------------------------------------------------------
# Phase 2: Subjective fit scoring
# ---------------------------------------------------------------------------

_FIT_SYSTEM = """You are a procurement scoring assistant.
Given a supplier profile and a list of subjective evaluation criteria, score how well the supplier meets the criteria.
Respond ONLY with a JSON object in exactly this schema — no extra keys, no markdown:

{
  "fit_score": <float 0.0 to 1.0>,
  "justification": "<one or two sentences>"
}

Rules:
- fit_score 1.0 = perfectly meets all criteria
- fit_score 0.0 = does not meet any criteria
- must_have criteria weigh more heavily than nice_to_have
- Be realistic and concise
"""


def llm_fit_score(
    supplier_profile: dict,
    criteria: list[SubjectiveCriterion],
) -> FitScoreResult:
    """Score a supplier against subjective criteria.

    Falls back to fit_score=0.5 on any failure.
    """
    if not criteria or not config.LLM_ENABLED:
        return FitScoreResult(score=0.5, rationale="No criteria or LLM disabled", success=False)

    criteria_text = "\n".join(
        f"- [{c.importance}] {c.criterion}" for c in criteria
    )
    user_msg = (
        f"Supplier profile:\n{json.dumps(supplier_profile, indent=2)}\n\n"
        f"Evaluation criteria:\n{criteria_text}"
    )

    raw = _call_llm([
        {"role": "system", "content": _FIT_SYSTEM},
        {"role": "user", "content": user_msg},
    ])
    if raw is None:
        return FitScoreResult(score=0.5, rationale="LLM unavailable", success=False)

    try:
        data = json.loads(raw)
        score = float(data.get("fit_score", 0.5))
        score = max(0.0, min(1.0, score))
        justification = str(data.get("justification", ""))
        return FitScoreResult(score=score, rationale=justification, success=True)
    except Exception as exc:
        logger.warning("Failed to parse LLM fit score response: %s", exc)
        return FitScoreResult(score=0.5, rationale="LLM parse error", success=False)
