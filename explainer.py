import json
import os

from groq import Groq

MODEL = "llama-3.3-70b-versatile"

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


SYSTEM_PROMPT = """You are a procurement intelligence assistant. You explain automated sourcing decisions to procurement managers and business stakeholders in clear, professional language. Be specific: reference supplier names, exact prices, policy rule IDs, and scores. Avoid generic filler. Format your response in markdown."""

USER_PROMPT_TEMPLATE = """Below is a structured procurement decision produced by an automated sourcing agent. Explain the decision in a way that a procurement manager or business stakeholder can immediately understand and act on.

{request_block}

Procurement decision JSON:
```json
{output_json}
```

Produce a markdown explanation with exactly these five sections:

## Decision Summary
2-3 sentences: what was requested, what the system decided (can_proceed or cannot_proceed), and the primary reason.

## Top Recommendation
Explain why the #1 ranked supplier was selected. Reference its price, quality/risk/ESG scores, preferred status, and incumbent status. Note any caveats (e.g. lead time issues, budget gap).

## Alternatives
For each remaining shortlisted supplier (rank 2+): one paragraph per supplier explaining why it ranked lower and what tradeoffs it presents versus #1.

## Excluded Suppliers
For each excluded supplier: one bullet explaining the specific constraint(s) that disqualified it (restricted flag, risk threshold, geography, capacity, etc.).

## Escalations
For each escalation: one bullet stating — what triggered it, who must act (escalate_to), and whether it is blocking. Use the rule ID (e.g. AT-002, ER-004).

Keep the total response focused and professional. Do not add extra sections."""


def explain_decision(output_json: dict, request_text: str | None = None) -> str:
    request_block = ""
    if request_text:
        request_block = f"Original request text: \"{request_text}\"\n\n"

    prompt = USER_PROMPT_TEMPLATE.format(
        request_block=request_block,
        output_json=json.dumps(output_json, indent=2),
    )

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=900,
        temperature=0.2,
    )

    return response.choices[0].message.content
