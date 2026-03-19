import json
import os

from groq import Groq
import groq

MODEL = "qwen/qwen3-32b"

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


SYSTEM_PROMPT = """/no_think You are a procurement intelligence assistant. You explain automated sourcing decisions to procurement managers and business stakeholders in clear, professional language. Be specific: reference supplier names, exact prices, policy rule IDs, and scores. Avoid generic filler. Format your response in markdown.

Write like a thoughtful human procurement colleague, not like a machine. The explanation should feel grounded, practical, and empathetic to the requester: explain not only what happened, but why it matters, what tradeoff is being made, and what a human should understand before acting. Keep the tone natural and businesslike. Do not mention being an AI."""

USER_PROMPT_TEMPLATE = """Procurement decision JSON:
```json
{output_json}
```

Explain this decision concisely for a procurement manager. Use exactly these sections:

## Decision Summary
2-3 sentences: what was requested, what the system decided (can_proceed or cannot_proceed), and the primary reason. Make this read like a concise human executive summary.

## Top Recommendation
Explain why the #1 ranked supplier was selected. Reference its price, quality/risk/ESG scores, preferred status, and incumbent status. Note any caveats (e.g. lead time issues, budget gap). Add the human rationale behind the choice: why this option is the most defensible or practical despite its limitations.

## Alternatives
For each remaining shortlisted supplier (rank 2+): one paragraph per supplier explaining why it ranked lower and what tradeoffs it presents versus #1. Make the tradeoffs easy for a human decision-maker to understand.

## Excluded Suppliers
For each excluded supplier: one bullet explaining the specific constraint(s) that disqualified it (restricted flag, risk threshold, geography, capacity, etc.), and why that exclusion is reasonable from a procurement perspective.

## Escalations
For each escalation: one bullet stating what triggered it, who must act (escalate_to), whether it is blocking, and why a human intervention is needed. Use the rule ID (e.g. AT-002, ER-004).

Keep the total response focused and professional. Do not add extra sections. Do not turn the answer into bullets everywhere; prefer short natural paragraphs inside the required sections."""


def explain_decision(output_json: dict, request_text: str | None = None) -> str:
    prompt = USER_PROMPT_TEMPLATE.format(
        output_json=json.dumps(output_json, indent=2),
    )

    client = _get_client()
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1800,
            temperature=0.2,
        )
    except groq.RateLimitError as e:
        raise RuntimeError(f"Rate limit reached: {e}") from e
    except groq.InternalServerError as e:
        raise RuntimeError(f"Model unavailable (over capacity or down): {e}") from e

    return response.choices[0].message.content
