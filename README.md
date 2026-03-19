# ChainIQ Sourcing Intelligence — StartHack 2026

Audit-ready autonomous sourcing agent for ChainIQ's procurement challenge at StartHack 2026 (St. Gallen, March 19–21).

## What it does

Converts an unstructured purchase request into a structured, defensible supplier comparison:

1. Parses free-text requests (LLM) → structured `request_json`
2. Validates completeness and detects contradictions
3. Applies procurement policies (approval thresholds, restricted suppliers, category/geography rules)
4. Filters and ranks suppliers deterministically (3-phase engine)
5. Presents results in a split-screen UI: structured output panel + chat Q&A
6. Resolves escalations via inline chat, rechecks policy after every update
7. Shows a "Forward request to supplier" CTA when no blocking escalations remain

## Stack

- **Backend**: FastAPI (Python 3.13) + Uvicorn
- **LLM**: Groq API — `qwen/qwen3-32b`
- **Frontend**: Single-page HTML + Tailwind CSS (CDN) + vanilla JS

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# add GROQ_API_KEY to .env
uvicorn app:app --reload
```

Open `http://localhost:8000`.

## Data

| File | Description |
|------|-------------|
| `data/suppliers.csv` | 151 suppliers — quality, risk, ESG scores, preferred/restricted flags |
| `data/pricing.csv` | 599 pricing rows — volume tiers, lead times |
| `data/policies.json` | Approval thresholds, escalation rules, category/geography rules |
| `data/requests.json` | Sample purchase requests (standard, missing_info, contradictory, etc.) |
| `data/historical_awards.csv` | 590 historical award records |
| `data/categories.csv` | 30 procurement categories |

## UI flow

1. Enter a free-text purchase request → parsed + validated
2. If required fields are missing, a chat collects them
3. Results appear in split-screen: structured supplier comparison (left) + chat (right)
4. Ask follow-up questions or resolve escalations via chat — suggestion chips appear after every response for quick navigation
5. Policy is rechecked after every update; "Forward request to supplier" button appears immediately when clear to proceed

## Key files

| File | Role |
|------|------|
| `app.py` | FastAPI endpoints |
| `engine/` | 3-phase processing engine (parse → filter → score/rank → output) |
| `results_chat.py` | Chat agent for results Q&A and escalation resolution |
| `chatbot.py` | Validation + escalation resolution chat |
| `static/index.html` | Full UI |
