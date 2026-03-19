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

Set "resolved": true only if you believe ALL outstanding issues are now addressed.
The server will verify this — your resolved claim may be overridden."""


def run_chat_turn(messages: list[dict], request_json: dict, issues: list[dict], original_request_text: str = "", field_provenance: dict | None = None) -> dict:
    issues_summary = "\n".join(
        f"- [{i.get('issue_id', '?')}] {i.get('field', '?')}: {i.get('description', '')}"
        for i in issues
    )

    # Summarize current request state so LLM knows what's already filled
    key_fields = {
        k: request_json.get(k)
        for k in ["quantity", "budget_amount", "category_l1", "category_l2",
                   "delivery_countries", "currency", "required_by_date",
                   "preferred_supplier_mentioned", "incumbent_supplier",
                   "unit_of_measure", "esg_requirement", "data_residency_constraint"]
    }
    request_summary = json.dumps(key_fields, ensure_ascii=False)

    system = _SYSTEM_PROMPT + f"\n\nCurrent request state (fields already captured):\n{request_summary}\n\nOutstanding issues to resolve:\n{issues_summary}"

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
    }
    updated_request = dict(request_json)
    updated_provenance = dict(field_provenance or {})
    for k, v in field_updates.items():
        if k in allowed or k in updated_request:
            updated_request[k] = v
            updated_provenance[k] = "user_stated"

    _normalize_fields(updated_request)

    # Server-side re-validation overrides LLM's resolved claim
    valid, remaining_issues = validate_request(updated_request, original_request_text)

    if valid:
        reply = (
            "Everything looks good! Would you like to add anything else, "
            "or shall I submit the request now?"
        )

    return {
        "reply": reply,
        "updated_request_json": updated_request,
        "updated_field_provenance": updated_provenance,
        "remaining_issues": remaining_issues,
        "resolved": valid,
    }
