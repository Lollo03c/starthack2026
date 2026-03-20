"""
Client Simulator: simulates a cooperative business stakeholder responding
to procurement escalation questions. Used by the "Ask the Client" button.
"""
import json
import os

from groq import Groq

MODEL = "qwen/qwen3-32b"

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


_RULE_HINTS = {
    "ER-001": "The procurement team says the budget is insufficient to cover the top supplier's price. Suggest increasing the budget to cover the recommended supplier, or agree to reduce quantity.",
    "ER-009": "There is a conflict with the mandated supplier (e.g. restricted, not available). Agree to drop the exclusive supplier mandate so alternatives can be considered.",
    "ER-010": "The mandated supplier is not the best option. Approve shipping with the recommended alternative supplier instead.",
    "ER-011": "A better-ranked supplier is available than the one you requested. Acknowledge this and approve switching to the better supplier.",
}

_SYSTEM_PROMPT = """/no_think You are simulating a cooperative business stakeholder who submitted a purchase request to the procurement team. The procurement team found an issue that needs your input.

Respond briefly and helpfully as the original requester would. Be cooperative — you want the procurement to succeed. Keep your response to 1-3 sentences.

You MUST respond with valid JSON:
{"message": "<your response as the client>", "field_updates": {}}

field_updates should contain any changes you're agreeing to:
- Budget increase: {"budget_amount": <new_amount>}
- Quantity reduction: {"quantity": <new_quantity>}
- Drop supplier mandate: {"supplier_must_use": false}
- Accept alternative: {"supplier_must_use": false, "preferred_supplier_mentioned": "<supplier_name>"}
- General acknowledgement with no field change: {}
"""


def simulate_client_response(
    escalation_rule: str,
    escalation_trigger: str,
    request_json: dict,
    output_json: dict,
) -> dict:
    """Simulate a client responding to an escalation question."""

    hint = _RULE_HINTS.get(escalation_rule, "Respond cooperatively to resolve this issue.")

    # Build context about the request
    context_parts = []
    interp = output_json.get("request_interpretation", {})
    context_parts.append(f"Original request: quantity={interp.get('quantity')}, budget={interp.get('budget_amount')}, "
                         f"category={interp.get('category_l1')}/{interp.get('category_l2')}, "
                         f"preferred_supplier={interp.get('preferred_supplier_stated')}")

    # Include top supplier info for budget escalations
    shortlist = output_json.get("supplier_shortlist", [])
    if shortlist:
        top = shortlist[0]
        context_parts.append(f"Top recommended supplier: {top.get('supplier_name')} at EUR {top.get('total_price_eur')} total "
                             f"(EUR {top.get('unit_price_eur')} per unit)")

    system = _SYSTEM_PROMPT + f"\n\nHint for this scenario: {hint}"
    user_msg = f"Escalation: {escalation_trigger}\n\nRequest context:\n" + "\n".join(context_parts)

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        max_tokens=500,
        temperature=0.3,
    )

    raw = json.loads(response.choices[0].message.content)
    return {
        "message": raw.get("message", "I understand. Please proceed as recommended."),
        "field_updates": raw.get("field_updates", {}),
    }


_FIELD_HINTS = {
    "quantity": "Provide a specific number (e.g. 500 units). Be realistic for business purchasing.",
    "category_l1": "Pick one of: IT Hardware & Software, Facilities & Office, Professional Services, Marketing & Events.",
    "category_l2": "Pick a sub-category that matches the L1 category (e.g. 'Laptops & Desktops' under IT Hardware & Software).",
    "delivery_countries": "Provide exactly ONE country as a 2-letter ISO code (e.g. 'DE' for Germany, 'CH' for Switzerland, 'US' for United States). Return as a list with one element.",
}

_FIELD_SYSTEM_PROMPT = """/no_think You are simulating a cooperative business stakeholder who submitted a purchase request to the procurement team. The procurement team needs a missing detail from you.

Respond briefly and helpfully as the original requester would. Be cooperative — you want the procurement to succeed. Keep your response to 1-2 sentences.

You MUST respond with valid JSON:
{"message": "<your response as the client>", "field_updates": {"<field_name>": <value>}}

field_updates MUST contain the field that was asked about with an appropriate value.
"""


def simulate_client_field_response(
    field: str,
    question: str,
    request_json: dict,
) -> dict:
    """Simulate a client providing a missing field value."""

    hint = _FIELD_HINTS.get(field, "Provide a reasonable value for this field.")

    # Build context about what's already known
    context_parts = []
    for k, v in request_json.items():
        if v is not None and v != "" and v != []:
            context_parts.append(f"  {k}: {v}")
    context_str = "\n".join(context_parts) if context_parts else "  (minimal info provided)"

    system = _FIELD_SYSTEM_PROMPT + f"\nField needed: {field}\nHint: {hint}"
    user_msg = f"Question from procurement team: {question}\n\nWhat we already know about the request:\n{context_str}"

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        max_tokens=300,
        temperature=0.3,
    )

    raw = json.loads(response.choices[0].message.content)
    return {
        "message": raw.get("message", "Sure, let me provide that detail."),
        "field_updates": raw.get("field_updates", {}),
    }
