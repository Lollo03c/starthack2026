import json
import os
import sys
from pathlib import Path

from groq import Groq

from validation import validate_request

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from extract_request import _normalize_fields  # noqa: E402

MODEL = "qwen/qwen3-32b"

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


_SYSTEM_PROMPT = """/no_think You are a procurement intake assistant helping a user complete a purchase request form.

Your rules:
- Ask the user EXACTLY ONE clarifying question per turn — the most critical outstanding issue
- Never invent or assume field values; only use what the user explicitly states
- Extract field values from the user's reply and put them in field_updates
- Be concise and professional

You MUST respond with valid JSON (no other text):
{
  "reply": "<your conversational response + next question>",
  "field_updates": { "<field_name>": <value> },
  "resolved": false
}

Field types for field_updates:
- quantity: number
- budget_amount: number (strip currency symbols, e.g. "€400k" → 400000)
- required_by_date: ISO date string (YYYY-MM-DD)
- category_l1: string (e.g. "IT", "Facilities", "Marketing")
- category_l2: string (e.g. "Laptops", "Office Supplies", "Consulting")
- delivery_countries: array of strings (e.g. ["Switzerland"])
- currency: string (e.g. "EUR", "CHF")
- preferred_supplier_mentioned: string (supplier name) or null
- incumbent_supplier: string (supplier name) or null
- unit_of_measure: string
- esg_requirement: boolean (true/false)
- data_residency_constraint: boolean (true/false)
- escalation_overrides: object with boolean flags, e.g. {"threshold_exceeded": true, "restricted_supplier": true, "single_supplier_risk": true, "data_residency": true, "usd_compliance": true}

ESCALATION RESOLUTION RULES (applies when issues have type "escalation"):
- ER-003 (value_exceeds_threshold): If user confirms they have approval authority or that approval has been obtained, set escalation_overrides.threshold_exceeded = true
- ER-002 (preferred_supplier_restricted): If user wants to override the restriction, set escalation_overrides.restricted_supplier = true. If user wants to switch supplier, update preferred_supplier_mentioned to the new supplier name.
- ER-004 (budget_insufficient): If user increases budget, update budget_amount. If user reduces quantity, update quantity. Calculate: if new budget / unit_price >= quantity (or new quantity <= budget / unit_price), the issue is resolved.
- ER-005 (data_residency_constraint_conflict): If user removes the constraint, set data_residency_constraint = false. If user wants to proceed anyway, set escalation_overrides.data_residency = true.
- ER-006 (single_supplier_capacity_risk): If user acknowledges and wants to proceed, set escalation_overrides.single_supplier_risk = true.
- ER-008 (usd_compliance): If user changes currency, update currency field. If user acknowledges and wants to proceed, set escalation_overrides.usd_compliance = true.

CRITICAL: After acknowledging a resolution, ALWAYS present the NEXT outstanding issue AND its options in the SAME reply. NEVER write a transition sentence ("let's move to the next", "I'll proceed", "understood, moving on") without immediately following it with the next issue description and what the user can do. The user must never need to send a blank prompt to see the next question.

Set "resolved": true only if you believe ALL outstanding issues are now addressed (either resolved by field update or acknowledged via escalation_overrides).
The server will verify this — your resolved claim may be overridden."""


def run_chat_turn(messages: list[dict], request_json: dict, issues: list[dict], original_request_text: str = "", field_provenance: dict | None = None, supplier_shortlist: list | None = None) -> dict:
    issues_summary = "\n".join(
        f"- [{i.get('issue_id', '?')}] ({i.get('type', 'validation')}) {i.get('description', '')} | action: {i.get('action_required', '')}"
        for i in issues
    )

    # Summarize current request state so LLM knows what's already filled
    key_fields = {
        k: request_json.get(k)
        for k in ["quantity", "budget_amount", "category_l1", "category_l2",
                   "delivery_countries", "currency", "required_by_date",
                   "preferred_supplier_mentioned", "incumbent_supplier",
                   "unit_of_measure", "esg_requirement", "data_residency_constraint",
                   "escalation_overrides"]
    }
    request_summary = json.dumps(key_fields, ensure_ascii=False)

    system = _SYSTEM_PROMPT + f"\n\nCurrent request state (fields already captured):\n{request_summary}\n\nOutstanding issues to resolve:\n{issues_summary}"

    # Inject supplier shortlist context for ER-002 resolution
    if supplier_shortlist:
        shortlist_names = [s.get("supplier_name", "") for s in supplier_shortlist if s.get("supplier_name")]
        if shortlist_names:
            system += f"\n\nAvailable compliant suppliers (alternatives if preferred supplier is restricted): {', '.join(shortlist_names[:5])}"

    groq_messages = [{"role": "system", "content": system}]
    for m in messages:
        if m.get("role") in ("user", "assistant"):
            groq_messages.append({"role": m["role"], "content": m["content"]})

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=groq_messages,
        response_format={"type": "json_object"},
        max_tokens=400,
        temperature=0.2,
    )

    raw = json.loads(response.choices[0].message.content)
    reply = raw.get("reply", "Could you clarify that for me?")
    field_updates = raw.get("field_updates", {})

    # Merge updates — only known fields to prevent unexpected mutation
    allowed = {
        "quantity", "budget_amount", "required_by_date", "category_l1",
        "category_l2", "delivery_countries", "currency",
        "preferred_supplier_mentioned", "incumbent_supplier",
        "unit_of_measure", "esg_requirement", "data_residency_constraint",
        "escalation_overrides",
    }
    updated_request = dict(request_json)
    updated_provenance = dict(field_provenance or {})
    for k, v in field_updates.items():
        if k in allowed or k in updated_request:
            updated_request[k] = v
            updated_provenance[k] = "user_stated"

    _normalize_fields(updated_request)

    # Server-side re-validation overrides LLM's resolved claim
    valid, remaining_struct_issues = validate_request(updated_request, original_request_text)

    # Check escalation issues: resolved if overridden or field updated
    escalation_issues_input = [i for i in issues if i.get("type") == "escalation"]
    pending_escalation_issues = _check_escalation_issues(escalation_issues_input, updated_request)
    non_escalation_issues_input = [i for i in issues if i.get("type") != "escalation"]

    # For escalation-only flows, resolved when no pending escalation issues remain
    if escalation_issues_input and not non_escalation_issues_input:
        all_resolved = valid and not pending_escalation_issues
        remaining_issues = remaining_struct_issues + pending_escalation_issues
    else:
        all_resolved = valid
        remaining_issues = remaining_struct_issues + pending_escalation_issues

    if all_resolved:
        reply = (
            "Everything looks good! Would you like to add anything else, "
            "or shall I re-submit the request now?"
            if escalation_issues_input else
            "Everything looks good! Would you like to add anything else, "
            "or shall I submit the request now?"
        )

    return {
        "reply": reply,
        "updated_request_json": updated_request,
        "updated_field_provenance": updated_provenance,
        "remaining_issues": remaining_issues,
        "resolved": all_resolved,
    }


def _check_escalation_issues(escalation_issues: list[dict], updated_request: dict) -> list[dict]:
    """Return escalation issues that are still unresolved after field updates / overrides."""
    overrides = updated_request.get("escalation_overrides") or {}
    rule_to_override = {
        "ER-003": "threshold_exceeded",
        "ER-002": "restricted_supplier",
        "ER-006": "single_supplier_risk",
        "ER-005": "data_residency",
        "ER-008": "usd_compliance",
    }
    pending = []
    for issue in escalation_issues:
        rule = issue.get("action_required", "")
        override_key = rule_to_override.get(rule)
        if override_key and overrides.get(override_key):
            continue  # Overridden — resolved
        # ER-004 budget: check if budget_amount was updated enough
        if "budget" in issue.get("description", "").lower() or "budget" in issue.get("action_required", "").lower():
            continue  # Budget changes re-evaluated by engine; treat as resolved from chat's perspective
        pending.append(issue)
    return pending
