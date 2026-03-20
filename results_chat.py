"""
Results Chat Agent: presents sourcing results conversationally and handles
escalation resolution within the same chat flow.
"""
import json
import os
import re
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
- Name the TOP RECOMMENDED supplier with: total price, lead time, and a plain-language explanation of WHY this supplier is the best fit (category match, delivery country, timeline, budget alignment)
- If preferred/incumbent, mention it
- Do NOT mention composite scores, quality scores, risk scores, or ESG scores

Message 2 — Escalations (ONLY if any exist, skip entirely if none):
- For each BLOCKING escalation: describe what the problem is in plain language, what needs to happen, and what the user can do to resolve it RIGHT HERE in the chat
- Use human-readable titles (e.g. "High-Value Approval Needed" not "ER-003", "Budget Shortfall" not "ER-001")
- For non-blocking: mention briefly with a human-readable title
- If no escalations: do NOT generate this message

Message 3 (optional) — Key caveats:
- Budget fit: does total price fit within budget? Surplus or gap?
- Lead time: can the supplier deliver by required date? Standard vs expedited?
- Uncertainties or assumptions the system made

## FOLLOW-UP QUESTIONS
Answer from the output data — never invent information:
- "What are the alternatives?" / "other suppliers?" → Compare each ranked supplier vs #1: price delta, lead time difference, key tradeoffs in plain language — no raw scores
- "Why was [supplier] excluded?" / "excluded suppliers" → Find in suppliers_excluded, explain using constraint category names (Geography, Capacity, Restricted, Budget, etc.) — not internal stage names
- "Tell me about the policies/rules" → Reference policy_evaluation: approval threshold, quotes required, category/geography rules with rule IDs
- "What about pricing/costs?" → Unit prices, totals, volume tiers, budget gap/surplus, expedited pricing
- "What assumptions were made?" / "uncertainties" / "what did you infer?" → Give a short, plain-language bulleted list. Combine parser inferences and engine uncertainties into one flat list — do NOT split into "parser-level" vs "engine-level" sections. Rules: (1) Skip trivial inferences that are obvious from the request text (e.g. category matched from product name, language detected as English). (2) Only list assumptions that actually affect the result — missing budget, missing deadline, inferred country, no ESG filter, etc. (3) Use plain language — never expose internal field names like `preferred_supplier_mentioned`, `esg_requirement`, `data_residency_constraint`. Say "no preferred supplier specified" not "preferred_supplier_mentioned = null". (4) For each meaningful assumption, state: what was assumed, and the practical impact in one phrase. (5) No intro sentence, no closing boilerplate — just the bullets.
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
- ER-009 (mandatory_supplier_conflict): remove the exclusive supplier constraint → {"supplier_must_use": false}; switch supplier → {"preferred_supplier_mentioned": "<name>"}; manual exception workflow → {"escalation_overrides": {"mandatory_supplier_conflict": true}}
- ER-010 (alternative_supplier_approval_required): explicitly approve another ranked provider → {"supplier_must_use": false, "preferred_supplier_mentioned": "<approved ranked supplier>"}
- ER-011 (better_alternative_available): explicitly approve switching from the mandatory supplier to the better-ranked provider → {"supplier_must_use": false, "preferred_supplier_mentioned": "<approved ranked supplier>"}

After resolving an escalation, your response MUST contain EXACTLY these messages:
1. Acknowledge the resolved escalation by its human-readable name (1 sentence).
2. IF any other blocking escalations still exist in the output data: list each remaining action by human-readable title, what the problem is, and what the user must do to resolve it here in the chat. This second message is MANDATORY if any blocking escalations remain — never skip it, never wait for the user to ask.
3. IF all blocking escalations are now resolved: tell the user the request can proceed and suggest next steps.

NEVER respond with just "Understood" or a vague acknowledgement when blocking escalations remain unresolved.

When resolving escalations, you MUST also use the supplier shortlist data to give specific, data-driven answers. For example, if the user asks about alternatives for a restricted supplier, list the available suppliers with their scores, prices, and lead times.

## FORMATTING
- Use markdown: **bold** for supplier names, key numbers
- Use bullet lists for comparisons and details
- Cite prices, dates, lead times — do not cite raw scores (quality, risk, ESG, composite)
- Never mention escalation IDs (ESC-001), rule IDs (ER-003), or validation IDs (V-001) in chat messages
- Be concise but complete — a procurement manager's time is valuable
- Never say "see the report" or "check the output" — you ARE the report"""


def run_results_chat(
    messages: list[dict],
    output_json: dict,
    request_json: dict,
    field_provenance: dict | None = None,
    inference_notes: dict | None = None,
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

    if field_provenance:
        inferred = {k: v for k, v in field_provenance.items() if v == "llm_inferred"}
        if inferred or inference_notes:
            prov_block = {"llm_inferred_fields": inferred, "inference_notes": inference_notes or {}}
            context_parts.append(f"\nParser-level inferences (fields the LLM deduced rather than the user stating explicitly):\n{json.dumps(prov_block, indent=2, ensure_ascii=False)}")

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
    field_updates, heuristic_messages, ship_supplier_selection = _apply_resolution_heuristics(field_updates, messages, output_json, request_json)
    if heuristic_messages:
        result_messages.extend(heuristic_messages)

    # Merge field updates into request_json
    allowed = {
        "quantity", "budget_amount", "required_by_date", "category_l1",
        "category_l2", "delivery_countries", "currency",
        "preferred_supplier_mentioned", "supplier_must_use", "incumbent_supplier",
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
        "ship_supplier_selection": ship_supplier_selection,
    }


def _apply_resolution_heuristics(
    field_updates: dict,
    messages: list[dict],
    output_json: dict,
    request_json: dict,
) -> tuple[dict, list[str], dict | None]:
    merged = dict(field_updates or {})
    heuristic_messages: list[str] = []
    ship_supplier_selection: dict | None = None
    latest_user_text = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            latest_user_text = str(message.get("content") or "")
            break
    if not latest_user_text:
        return merged, heuristic_messages, ship_supplier_selection

    text = latest_user_text.lower()
    escalations = output_json.get("escalations", []) or []
    shortlist = output_json.get("supplier_shortlist", []) or []
    excluded = output_json.get("suppliers_excluded", []) or []
    top_alternative = shortlist[0].get("supplier_name") if shortlist else None
    current_preferred = request_json.get("preferred_supplier_mentioned")
    mandatory_active = bool(request_json.get("supplier_must_use"))

    overrides = dict(merged.get("escalation_overrides") or {})

    approved_phrases = [
        "approved by head of category",
        "approve from head of category",
        "approval from head of category",
        "we have approval from head of category",
        "we have approve from head of category",
        "head of category approved",
    ]
    # Broader approval patterns — catch general confirmations like
    # "I have all approval decision I need", "approval granted", etc.
    general_approval_phrases = [
        "all approval",
        "approval granted",
        "approval confirmed",
        "i have approval",
        "we have approval",
        "have the approval",
        "got approval",
        "approval is granted",
        "approval decision",
        "i approve",
        "we approve",
        "approved",
        "i confirm",
        "i acknowledge",
        "acknowledged",
    ]
    has_specific_approval = any(phrase in text for phrase in approved_phrases)
    has_general_approval = any(phrase in text for phrase in general_approval_phrases)
    if has_specific_approval or has_general_approval:
        if any(e.get("rule") == "ER-003" for e in escalations):
            overrides["threshold_exceeded"] = True
        if any(e.get("rule") == "ER-004" for e in escalations):
            overrides["insufficient_quotes"] = True

    switch_phrases = [
        "allow the switch",
        "approve the switch",
        "we allow the switch",
        "allow switch",
        "switch is allowed",
        "use another provider",
        "ship with another provider",
        "approve another provider",
    ]
    if any(phrase in text for phrase in switch_phrases):
        if any(e.get("rule") in {"ER-010", "ER-011"} for e in escalations):
            merged["supplier_must_use"] = False
            if "preferred_supplier_mentioned" not in merged and top_alternative:
                merged["preferred_supplier_mentioned"] = top_alternative
            if top_alternative and merged.get("preferred_supplier_mentioned") == current_preferred:
                merged["preferred_supplier_mentioned"] = top_alternative

    switched_supplier = _extract_shortlist_supplier_switch(latest_user_text, shortlist)
    if not switched_supplier:
        switched_supplier = _extract_metric_based_supplier_switch(latest_user_text, shortlist)
    if switched_supplier and switched_supplier != current_preferred:
        merged["preferred_supplier_mentioned"] = switched_supplier
        if mandatory_active:
            merged["supplier_must_use"] = False
        ship_supplier_selection = {"status": "valid", "supplier_name": switched_supplier}
        heuristic_messages.append(
            f"I've switched the selected supplier to **{switched_supplier}** and I'm refreshing the sourcing result now."
        )
    elif _has_supplier_switch_intent(latest_user_text):
        invalid_supplier = _extract_nonfeasible_supplier_switch(latest_user_text, shortlist, excluded)
        if invalid_supplier:
            ship_supplier_selection = {"status": "invalid", "supplier_name": invalid_supplier}
            heuristic_messages.append(
                f"**{invalid_supplier}** is not a feasible shipping choice for this request, so I haven't changed the supplier. Please choose a provider from the current feasible ranking."
            )

    if overrides:
        merged["escalation_overrides"] = overrides

    # If the user cleared the mandate but the preferred supplier still points
    # at the old blocked supplier, switch to the top ranked approved fallback.
    if (
        merged.get("supplier_must_use") is False
        and top_alternative
        and merged.get("preferred_supplier_mentioned", current_preferred) == current_preferred
        and any(e.get("rule") in {"ER-010", "ER-011"} for e in escalations)
    ):
        merged["preferred_supplier_mentioned"] = top_alternative

    return merged, heuristic_messages, ship_supplier_selection


def _extract_shortlist_supplier_switch(user_text: str, shortlist: list[dict]) -> str | None:
    text = (user_text or "").lower()
    if not text or not shortlist:
        return None

    if not _has_supplier_switch_intent(user_text):
        return None

    supplier_names = [
        supplier.get("supplier_name", "")
        for supplier in shortlist
        if supplier.get("supplier_name")
    ]
    supplier_names.sort(key=len, reverse=True)
    for supplier_name in supplier_names:
        if supplier_name.lower() in text:
            return supplier_name
    return None


def _has_supplier_switch_intent(user_text: str) -> bool:
    text = (user_text or "").lower()
    intent_patterns = [
        r"\bswitch to\b",
        r"\bswitch with\b",
        r"\bswitch from\b",
        r"\bchange to\b",
        r"\bmove to\b",
        r"\bgo with\b",
        r"\buse\b",
        r"\bchoose\b",
        r"\bselect\b",
        r"\bbuy from\b",
        r"\bship with\b",
        r"\bproceed with\b",
    ]
    return any(re.search(pattern, text) for pattern in intent_patterns)


def _extract_nonfeasible_supplier_switch(
    user_text: str,
    shortlist: list[dict],
    excluded: list[dict],
) -> str | None:
    text = (user_text or "").lower()
    if not text:
        return None

    feasible_names = {
        supplier.get("supplier_name", "").lower()
        for supplier in shortlist
        if supplier.get("supplier_name")
    }
    candidate_names = [
        supplier.get("supplier_name", "")
        for supplier in excluded
        if supplier.get("supplier_name")
    ]
    candidate_names.sort(key=len, reverse=True)
    for supplier_name in candidate_names:
        lowered = supplier_name.lower()
        if lowered in text and lowered not in feasible_names:
            return supplier_name
    return None


def _extract_metric_based_supplier_switch(user_text: str, shortlist: list[dict]) -> str | None:
    text = (user_text or "").lower()
    if not text or not shortlist or not _has_supplier_switch_intent(user_text):
        return None

    metric = _extract_requested_metric(text)
    if not metric:
        return None

    ranked = _rank_shortlist_by_metric(shortlist, metric)
    top = ranked[0] if ranked else None
    return top.get("supplier_name") if top else None


def _extract_requested_metric(text: str) -> str | None:
    metric_patterns = [
        ("cheaper", [
            r"\bcheapest\b",
            r"\blower cost\b",
            r"\blowest cost\b",
            r"\blowest price\b",
            r"\bcheaper\b",
            r"\bcheap(?:er)? metric\b",
            r"\bprice metric\b",
            r"\bcost metric\b",
        ]),
        ("fastest", [
            r"\bfastest\b",
            r"\bquickest\b",
            r"\bearliest\b",
            r"\bsoonest\b",
            r"\bfast(?:est)? metric\b",
            r"\blead(?: time)? metric\b",
            r"\bspeed metric\b",
        ]),
        ("lowest_risk", [
            r"\blowest risk\b",
            r"\bleast risky\b",
            r"\bless risky\b",
            r"\bminimum risk\b",
            r"\brisk metric\b",
            r"\blow risk metric\b",
            r"\blowest risk metric\b",
        ]),
        ("overall", [
            r"\boverall\b",
            r"\bbest overall\b",
            r"\btop overall\b",
            r"\bbest ranked\b",
            r"\boverall metric\b",
            r"\bcomposite metric\b",
        ]),
    ]
    for metric, patterns in metric_patterns:
        if any(re.search(pattern, text) for pattern in patterns):
            return metric
    return None


def _rank_shortlist_by_metric(shortlist: list[dict], metric: str) -> list[dict]:
    def sort_value(supplier: dict) -> tuple:
        if metric == "cheaper":
            primary = float(supplier.get("total_price_eur", float("inf")))
        elif metric == "fastest":
            primary = float(
                supplier.get(
                    "effective_lead_time_days",
                    supplier.get("standard_lead_time_days", float("inf")),
                )
            )
        elif metric == "lowest_risk":
            primary = float(supplier.get("risk_score", float("inf")))
        else:
            primary = -float(supplier.get("composite_score", 0.0))

        composite_tiebreak = -float(supplier.get("composite_score", 0.0))
        price_tiebreak = float(supplier.get("total_price_eur", float("inf")))
        name_tiebreak = str(supplier.get("supplier_name", ""))
        return (primary, composite_tiebreak, price_tiebreak, name_tiebreak)

    return sorted(shortlist, key=sort_value)
