import json
import os
from datetime import date

from groq import Groq

MODEL = "llama-3.3-70b-versatile"

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


_REQUIRED_FIELDS = [
    "quantity",
    "budget_amount",
    "required_by_date",
    "category_l1",
    "category_l2",
    "delivery_countries",
]

_FIELD_QUESTIONS = {
    "quantity": "How many units do you need?",
    "budget_amount": "What is your total budget for this purchase (please give a number)?",
    "required_by_date": "When do you need delivery by? (e.g. April 30, 2026)",
    "category_l1": "What high-level category is this purchase? (e.g. IT, Facilities, Marketing)",
    "category_l2": "What specific sub-category? (e.g. Laptops, Office Supplies, Consulting)",
    "delivery_countries": "Which country or countries should this be delivered to?",
}


def validate_structure(data: dict) -> list[dict]:
    issues = []
    counter = 1
    for field in _REQUIRED_FIELDS:
        val = data.get(field)
        empty = val is None or val == "" or val == [] or (isinstance(val, str) and not val.strip())
        if empty:
            issues.append({
                "issue_id": f"VAL-{counter:03d}",
                "severity": "error",
                "type": "missing_field",
                "field": field,
                "description": f"Required field '{field}' is missing or empty.",
                "question_for_user": _FIELD_QUESTIONS.get(field, f"Please provide the {field}."),
            })
            counter += 1
    return issues


_SEMANTIC_SYSTEM = """You are a procurement validation assistant. Detect semantic issues in a parsed purchase request.

Check only for:
1. budget_scope_ambiguity: ONLY flag when the text contains contradictory per-unit and total-budget signals (e.g. "€800 per unit, total €400k for 500 units" where 800×500≠400k). Do NOT flag when the text says "budget X" or "total budget X" — those are unambiguously total. Do NOT flag solely because unit price could be computed.
2. supplier_contradiction: contradictory supplier constraints (e.g. two mutually exclusive requirements).
3. deadline_past: required_by_date is before today ({today}).
4. unit_price_implausible: implied unit price (budget_amount / quantity) is wildly implausible for the category (e.g. €0.50 per laptop or €500,000 per pen).

Return ONLY valid JSON: {{"issues": [...]}}

Each issue:
{{
  "issue_id": "VAL-SEM-001",
  "severity": "error" or "warning",
  "type": "ambiguous" or "contradictory",
  "field": "<field name>",
  "description": "<clear one-sentence description>",
  "question_for_user": "<one direct clarifying question>"
}}

If no semantic issues found, return {{"issues": []}}. Do not fabricate issues."""


def validate_semantics(request_json: dict, original_text: str) -> list[dict]:
    today = date.today().isoformat()
    system = _SEMANTIC_SYSTEM.format(today=today)

    user_content = (
        f'Original request text: "{original_text}"\n\n'
        f"Parsed request JSON:\n{json.dumps(request_json, indent=2)}"
    )

    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            max_tokens=600,
            temperature=0.1,
        )
        data = json.loads(response.choices[0].message.content)
        return data.get("issues", [])
    except Exception:
        return []


def validate_request(data: dict, original_text: str) -> tuple[bool, list[dict]]:
    struct_issues = validate_structure(data)
    sem_issues = validate_semantics(data, original_text) if original_text else []
    all_issues = struct_issues + sem_issues
    valid = not any(i.get("severity") == "error" for i in all_issues)
    return valid, all_issues
