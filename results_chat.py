"""
Results Chat Agent: presents sourcing results conversationally and handles
escalation resolution within the same chat flow.
"""
import json
import os
import sys
from pathlib import Path

from groq import Groq

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from extract_request import _normalize_fields  # noqa: E402

MODEL = "qwen/qwen3-32b"

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


_SYSTEM_PROMPT = """/no_think You are a procurement intelligence assistant. You present sourcing analysis results conversationally and help resolve any escalation issues — all within the chat.

## RESPONSE FORMAT — MANDATORY
EVERY response MUST be a JSON object with this exact structure — no exceptions, even for short acknowledgements:
{"messages": ["<text>"], "field_updates": {}}

Rules:
- "messages" is ALWAYS a non-empty array of strings. Even a simple acknowledgement like "ok" must be wrapped: {"messages": ["Understood! Let me know if you have any other questions."], "field_updates": {}}
- "field_updates" is ALWAYS an object (use {} when no updates)
- NEVER respond with plain text outside the JSON structure
- Use multiple messages to break up information naturally (displayed as separate chat bubbles). Usually 2-3 messages for initial presentation, 1 for follow-ups.

field_updates: object of field changes when the user resolves escalations (see ESCALATION RESOLUTION). Leave as {} when just presenting or answering questions.

## INITIAL PRESENTATION (when the user message is "Present the sourcing results.")

Message 1 — Decision & Recommendation:
- Open with the decision status: can proceed / cannot proceed / proceed with conditions
- Name the TOP RECOMMENDED supplier with: total price, unit price, quality score, risk score, ESG score, lead time
- Explain WHY this supplier is the best fit: category match, delivery country, timeline, budget alignment
- If preferred/incumbent, mention it
- Mention the composite score

Message 2 — Escalations (ONLY if any exist, skip entirely if none):
- For each BLOCKING escalation: state rule ID, what triggered it, who needs to act, and what the user can do to resolve it RIGHT HERE in the chat
- For non-blocking: mention briefly
- If no escalations: do NOT generate this message

Message 3 (optional) — Key caveats:
- Budget fit: does total price fit within budget? Surplus or gap?
- Lead time: can the supplier deliver by required date? Standard vs expedited?
- Uncertainties or assumptions the system made

## FOLLOW-UP QUESTIONS
Answer from the output data — never invent information:
- "What are the alternatives?" / "other suppliers?" → Compare each ranked supplier vs #1: price delta, score delta, lead time, pros/cons
- "Why was [supplier] excluded?" / "excluded suppliers" → Find in suppliers_excluded, explain filter stage and reason
- "Tell me about the policies/rules" → Reference policy_evaluation: approval threshold, quotes required, category/geography rules with rule IDs
- "What about pricing/costs?" → Unit prices, totals, volume tiers, budget gap/surplus, expedited pricing
- "What assumptions were made?" / "uncertainties" → List each uncertainty with its impact
- "Audit trail" / "what data was used?" → Policies checked, suppliers evaluated, data sources
- General questions → Answer from the data with specific numbers

## ESCALATION RESOLUTION
When the user wants to resolve an escalation, set field_updates:
- ER-001 (budget_insufficient): budget increase → {"budget_amount": <new>}; quantity reduction → {"quantity": <new>}
- ER-002 (restricted_supplier): override → {"escalation_overrides": {"restricted_supplier": true}}; switch → {"preferred_supplier_mentioned": "<name>"}
- ER-003 (value_exceeds_threshold): user confirms approval → {"escalation_overrides": {"threshold_exceeded": true}}
- ER-004 (insufficient_quotes): user acknowledges → {"escalation_overrides": {"insufficient_quotes": true}}
- ER-005 (data_residency): remove constraint → {"data_residency_constraint": false}; override → {"escalation_overrides": {"data_residency": true}}
- ER-006 (capacity_risk): override → {"escalation_overrides": {"single_supplier_risk": true}}
- ER-008 (usd_compliance): change currency → {"currency": "<new>"}; override → {"escalation_overrides": {"usd_compliance": true}}

After resolving an escalation, acknowledge it. If other escalations remain, present them. If all resolved, tell the user the request can now proceed.

When resolving escalations, you MUST also use the supplier shortlist data to give specific, data-driven answers. For example, if the user asks about alternatives for a restricted supplier, list the available suppliers with their scores, prices, and lead times.

## FORMATTING
- Use markdown: **bold** for supplier names, key numbers, rule IDs
- Use bullet lists for comparisons and details
- Every claim must cite a specific number — never be vague when data exists
- Be concise but complete — a procurement manager's time is valuable
- Never say "see the report" or "check the output" — you ARE the report"""


def run_results_chat(
    messages: list[dict],
    output_json: dict,
    request_json: dict,
) -> dict:
    """Run a results presentation / Q&A chat turn."""

    # Build context with the full output (selective — keep token count reasonable)
    context_parts = []

    rec = output_json.get("recommendation", {})
    context_parts.append(f"Recommendation:\n{json.dumps(rec, indent=2, ensure_ascii=False)}")

    interp = output_json.get("request_interpretation", {})
    context_parts.append(f"\nRequest interpretation:\n{json.dumps(interp, indent=2, ensure_ascii=False)}")

    shortlist = output_json.get("supplier_shortlist", [])
    context_parts.append(f"\nSupplier shortlist ({len(shortlist)} suppliers):\n{json.dumps(shortlist, indent=2, ensure_ascii=False)}")

    excluded = output_json.get("suppliers_excluded", [])
    context_parts.append(f"\nSuppliers excluded ({len(excluded)}):\n{json.dumps(excluded, indent=2, ensure_ascii=False)}")

    escalations = output_json.get("escalations", [])
    context_parts.append(f"\nEscalations ({len(escalations)}):\n{json.dumps(escalations, indent=2, ensure_ascii=False)}")

    validation = output_json.get("validation", {})
    context_parts.append(f"\nValidation:\n{json.dumps(validation, indent=2, ensure_ascii=False)}")

    policy = output_json.get("policy_evaluation", {})
    context_parts.append(f"\nPolicy evaluation:\n{json.dumps(policy, indent=2, ensure_ascii=False)}")

    uncertainties = output_json.get("uncertainties", [])
    if uncertainties:
        context_parts.append(f"\nUncertainties:\n{json.dumps(uncertainties, indent=2, ensure_ascii=False)}")

    audit = output_json.get("audit_trail", {})
    context_parts.append(f"\nAudit trail:\n{json.dumps(audit, indent=2, ensure_ascii=False)}")

    # Current overrides
    overrides = request_json.get("escalation_overrides", {})
    if overrides:
        context_parts.append(f"\nCurrent escalation overrides: {json.dumps(overrides)}")

    system = _SYSTEM_PROMPT + "\n\n## SOURCING OUTPUT DATA\n" + "\n".join(context_parts)

    groq_messages = [{"role": "system", "content": system}]
    for m in messages:
        if m.get("role") in ("user", "assistant"):
            groq_messages.append({"role": m["role"], "content": m["content"]})

    # If no user messages in history, this is the initial presentation
    if not any(m.get("role") == "user" for m in messages):
        groq_messages.append({
            "role": "user",
            "content": "Present the sourcing results.",
        })

    client = _get_client()
    import logging
    _log = logging.getLogger(__name__)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=groq_messages,
            response_format={"type": "json_object"},
            max_tokens=2000,
            temperature=0.2,
        )
    except Exception as e:
        # Handle json_validate_failed: model generated plain text instead of JSON
        # Extract the failed_generation text and use it as the response
        err_str = str(e)
        if "json_validate_failed" in err_str or "failed_generation" in err_str:
            _log.warning("Groq json_validate_failed, extracting failed_generation: %s", err_str[:300])
            fallback_text = None
            # Extract from error body (preferred — structured access)
            if hasattr(e, 'body') and isinstance(e.body, dict):
                fallback_text = e.body.get('error', {}).get('failed_generation')
            if not fallback_text:
                fallback_text = "I understood your message. Let me know if you have any other questions about the sourcing results."
            raw = {"messages": [fallback_text], "field_updates": {}}
        else:
            _log.error("Groq API call failed in results_chat: %s", e, exc_info=True)
            raise
    else:
        raw_content = response.choices[0].message.content
        try:
            raw = json.loads(raw_content)
        except json.JSONDecodeError:
            _log.error("Failed to parse results_chat JSON: %s", raw_content[:500])
            import re
            cleaned = re.sub(r'<think>.*?</think>\s*', '', raw_content, flags=re.DOTALL).strip()
            try:
                raw = json.loads(cleaned)
            except json.JSONDecodeError:
                raise RuntimeError(f"LLM returned invalid JSON: {raw_content[:200]}")

    # Accept either "messages" (array) or "reply" (string) from LLM
    result_messages = raw.get("messages")
    if result_messages is None:
        result_messages = [raw.get("reply", "I couldn't generate the results summary.")]
    if isinstance(result_messages, str):
        result_messages = [result_messages]

    field_updates = raw.get("field_updates", {})

    # Merge field updates into request_json
    allowed = {
        "quantity", "budget_amount", "required_by_date", "category_l1",
        "category_l2", "delivery_countries", "currency",
        "preferred_supplier_mentioned", "incumbent_supplier",
        "unit_of_measure", "esg_requirement", "data_residency_constraint",
        "escalation_overrides",
    }
    updated_request = dict(request_json)
    has_updates = False
    for k, v in field_updates.items():
        if k in allowed:
            if k == "escalation_overrides":
                existing = updated_request.get("escalation_overrides", {}) or {}
                existing.update(v)
                updated_request[k] = existing
            else:
                updated_request[k] = v
            has_updates = True

    if has_updates:
        _normalize_fields(updated_request)

    return {
        "messages": result_messages,
        "updated_request_json": updated_request,
        "has_field_updates": has_updates,
    }
