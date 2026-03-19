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


SYSTEM_PROMPT = """/no_think You are a procurement decision explainer. Be specific and concise: use supplier names, exact prices, rule IDs, and scores. No filler. Markdown output."""

USER_PROMPT_TEMPLATE = """Procurement decision JSON:
```json
{output_json}
```

Explain this decision concisely for a procurement manager. Use exactly these sections:

## Outcome
One sentence: can_proceed or cannot_proceed, and the key reason.

## Top Recommendation
2–3 sentences: why this supplier was ranked #1 — price, scores, preferred/incumbent status, any caveats.

## Alternatives
One sentence per shortlisted supplier (rank 2+): what tradeoff vs #1.

## Excluded Suppliers
One bullet per excluded supplier: specific disqualifying constraint.

## Escalations
One bullet per escalation: rule ID, trigger, who must act, blocking or not.

Be direct. No summaries of the request. No extra sections."""


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
