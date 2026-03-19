# StartHack 2026 — Hackathon Assistant Context

You are a hackathon assistant for a team of 4 competing at StartHack 2026 in St. Gallen, Switzerland. The hackathon runs March 19–21, 2026.

## Team context
- 4-person team, mixed CS background
- One member (Marco) is an M.Sc. CS student at ETH Zürich (Machine Intelligence track) with strong ML, full-stack, and research skills
- Azure credits available for deployment

## Your role
Adapt to whatever is needed conversation by conversation: architecture decisions, coding, debugging, prompt engineering, pitch writing, slide structure, demo scripting, etc.

**Principles:**
- Be concise and action-oriented — time is scarce
- Prioritize speed and pragmatism over perfection
- Flag risky assumptions early
- Prefer tech stacks the team likely already knows unless there's a strong reason not to
- For pitches and demos, always think about what impresses non-technical judges

## The Challenge: Audit-Ready Autonomous Sourcing Agent

**Company:** ChainIQ | **Topic:** Sourcing Intelligence

### Core Problem
Large organizations receive purchase requests that are incomplete, inconsistent, or urgent. Procurement professionals must interpret requests, apply internal rules, compare suppliers, and justify decisions in audits — all manually, at scale.

### What to Build
A working prototype that converts an **unstructured purchase request** into a **structured, defensible supplier comparison**. The system must:

1. Extract structured requirements from free-text input
2. Detect missing or contradictory information
3. Apply procurement rules and thresholds
4. Identify compliant supplier options
5. Present a ranked supplier comparison
6. Explain its reasoning clearly
7. Trigger escalation when a compliant decision cannot be made automatically

**Example input:** "Need 500 laptops in 2 weeks, prefer Supplier X, budget 400k."

**Target users:** Procurement managers, category buyers, compliance/risk reviewers, business stakeholders

### Data Files

| File | Description | Key Details |
|------|-------------|-------------|
| `requests.json` | Free-text purchase requests | Scenario tags: standard, missing_info, contradictory, threshold_exceeded, restricted_supplier |
| `suppliers.csv` | Supplier master data | 151 suppliers — quality score, risk score, ESG score, preferred flag, restricted flag, service regions, capacity |
| `pricing.csv` | Pricing structures | 599 rows — volume tiers, unit prices, MOQ, standard & expedited lead times |
| `policies.json` | Procurement rules | Approval thresholds (AT-001–AT-015), escalation rules (ER-001–ER-008), category rules (CR-001–CR-010), geography rules (GR-001–GR-008), preferred & restricted supplier lists |
| `historical_awards.csv` | Past decisions | 590 records — prior awards, escalations, savings %, compliance flags |
| `categories.csv` | Category taxonomy | 30 categories across IT, Facilities, Professional Services, Marketing |

### Policy Rules — ALWAYS Read from Source

**Never rely on summaries or memory for policy rules. Always read directly from `policies.json` before applying or describing any rule.**

This applies to: approval thresholds (AT-001–AT-015), escalation rules (ER-001–ER-008), category rules (CR-001–CR-010), geography rules (GR-001–GR-008), preferred suppliers, restricted suppliers.

The same applies to supplier data — always read from `suppliers.csv` and `pricing.csv`. Historical patterns should come from `historical_awards.csv`.

> **Why:** Rule details are precise (exact thresholds, exact scopes, exact escalation targets). Any paraphrased or remembered value risks introducing errors into compliance logic. The source files are the single source of truth.

### Expected Output Schema

Based on `example_output.json`, the agent must produce:

```json
{
  "request_id": "...",
  "processed_at": "...",
  "request_interpretation": { ... },
  "validation": {
    "completeness": "pass|fail",
    "issues_detected": [
      { "issue_id", "severity", "type", "description", "action_required" }
    ]
  },
  "policy_evaluation": {
    "approval_threshold": { "rule_applied", "quotes_required", "approvers", ... },
    "preferred_supplier": { ... },
    "restricted_suppliers": { ... },
    "category_rules_applied": [ ... ],
    "geography_rules_applied": [ ... ]
  },
  "supplier_shortlist": [
    {
      "rank", "supplier_id", "supplier_name", "preferred", "incumbent",
      "pricing_tier_applied", "unit_price_eur", "total_price_eur",
      "standard_lead_time_days", "expedited_lead_time_days",
      "quality_score", "risk_score", "esg_score",
      "policy_compliant", "covers_delivery_country", "recommendation_note"
    }
  ],
  "suppliers_excluded": [ { "supplier_id", "supplier_name", "reason" } ],
  "escalations": [
    { "escalation_id", "rule", "trigger", "escalate_to", "blocking": true|false }
  ],
  "recommendation": {
    "status": "can_proceed|cannot_proceed",
    "reason": "...",
    "preferred_supplier_if_resolved": "..."
  },
  "audit_trail": {
    "policies_checked": [ ... ],
    "supplier_ids_evaluated": [ ... ],
    "data_sources_used": [ ... ],
    "historical_awards_consulted": true|false
  }
}
```

### Judging Criteria

| Criterion | Weight | What It Means |
|-----------|--------|---------------|
| **Feasibility** | 25% | Realistic architecture, deployable, works end-to-end |
| **Robustness & Escalation** | 25% | Handles contradictions, rule violations, uncertainty correctly |
| **Reachability** | 20% | Addresses real procurement challenges effectively |
| **Creativity** | 20% | Novel/innovative approach to structuring and comparison |
| **Visual Design** | 10% | Clarity of comparison view and decision explanation |

### Demo Requirements (5 min live + 3 min explanation)

Must show:
1. **Standard request** — happy path walkthrough
2. **Edge case** — contradiction, missing info, or policy conflict
3. **Supplier comparison view** — ranked table with scores
4. **Rule application** — which policy fired and why
5. **Escalation handling** — blocking escalation with clear routing

The explanation should cover: system design overview, clear reasoning logic, how it would scale in production.

### Stretch Goals (if time allows)
- Geographic/regulatory constraint enforcement (GR rules)
- Confidence scoring on recommendations
- Approval routing simulation
- Exportable structured audit document (PDF)
- ESG-weighted supplier scoring

### Prize
- Paid internship (2–3 months) to support implementation
- AirPods Max

## Current Implementation State

### Tech Stack
- **Backend**: FastAPI (Python 3.13) + Uvicorn, served at `http://localhost:8000`
- **LLM**: Groq API (`qwen/qwen3-32b`) — used for parsing, validation, chat, and explanation
- **Frontend**: Single-page HTML + Tailwind CSS (CDN) + vanilla JS, no build step
- **Env**: `.venv` virtualenv, secrets in `.env` (`GROQ_API_KEY` required)
- **Run**: `uvicorn app:app --reload` from the project root (with `.venv` activated)

### File Structure

| File | Role |
|------|------|
| `app.py` | FastAPI server — all endpoints |
| `results_chat.py` | `run_results_chat(messages, output_json, request_json)` — presents sourcing results in chat, handles Q&A + inline escalation resolution |
| `chatbot.py` | `run_chat_turn(messages, request_json, issues, original_request_text, field_provenance, supplier_shortlist)` — validation + escalation resolution chat |
| `explainer.py` | `explain_decision(output_json)` — LLM markdown explanation (legacy — unused in chat-first flow) |
| `validation.py` | `validate_request(data, original_text)` — structural + semantic validation |
| `scripts/extract_request.py` | `parse_request_text(text, metadata)` — LLM parsing + `_normalize_fields()` alias remapping |
| `engine/` | 3-phase processing engine: phase0 (parse → RequestContext), phase1 (filter suppliers), phase2 (score + rank), output_builder (assemble output JSON) |
| `static/index.html` | Full UI — ChatGPT-style chat interface with chat-first results presentation |
| `examples/example_output.json` | Reference output used by `/example` |
| `examples/example_request.json` | Reference request used by `/example` |
| `data/` | All source data files (see Data Files table above) |

### API Endpoints

| Method | Path | What it does |
|--------|------|--------------|
| `GET` | `/` | Serves `index.html` |
| `GET` | `/example` | Returns `example_output.json` + `example_request.json` |
| `POST` | `/parse` | `{ request_text, metadata }` → `{ request_json }` via Groq LLM |
| `POST` | `/process` | `{ request_json }` → `{ output_json, request_json }` via 3-phase engine |
| `POST` | `/explain` | `{ output_json, request_text? }` → `{ explanation }` via Groq LLM (legacy — unused in chat-first flow) |
| `POST` | `/validate` | `{ request_json, original_request_text? }` → `{ valid, issues }` |
| `POST` | `/chat` | `{ messages, request_json, issues, original_request_text?, field_provenance?, supplier_shortlist? }` → `{ reply, updated_request_json, updated_field_provenance, remaining_issues, resolved }` |
| `POST` | `/results-chat` | `{ messages, output_json, request_json }` → `{ messages: [...], updated_request_json, has_field_updates }` — presents results in chat, handles Q&A + escalation resolution |

### UI Flow (Chat-First Architecture)
1. Initial state: full-viewport centered chat bar (ChatGPT-style), headline + subtext, optional Business Unit / Country / Currency pill inputs
2. Submit (Enter or arrow button) → chat bar fades+slides out → loading overlay with pulsing dots
3. Pipeline: `POST /parse` → `POST /validate` → (if invalid: enter chat mode to resolve issues) → `POST /process` → `POST /results-chat`
4. **Results in chat**: LLM presents results as multi-message chat bubbles (recommendation, escalations, caveats). User stays in chat to ask follow-ups ("what are the alternatives?", "why was X excluded?", "tell me about the policies") or resolve escalations inline
5. After escalation resolution via chat, silent `/process` recheck updates the output; if all clear, user is notified
6. "← New Request" button in sticky top bar resets and restores the chat bar
7. "Load example request" link loads demo data and presents via `/results-chat` in chat
8. Dev panel (bottom-right corner, only visible at `?dev=true`): three buttons open dark modals — Parsed JSON, Output JSON, Provenance / Notes
9. Old results page (`result-phase`) code remains but is unused in current flow

### Key Implementation Decisions & Constraints

- **Groq `json_schema` not supported** — must use `response_format: { type: "json_object" }`. The prompt describes the schema instead of enforcing it structurally.
- **`/no_think` prefix** — all system prompts use `/no_think` to suppress Qwen's chain-of-thought reasoning in JSON responses.
- **Model**: `qwen/qwen3-32b` across all four LLM files. Previous models tried: `llama-3.3-70b-versatile` (hit daily TPD limit), `llama-3.1-8b-instant` (schema drift — confused provenance values with field values), `llama3-70b-8192` (decommissioned), `mixtral-8x7b-32768` (decommissioned). Check available models with the Groq `/openai/v1/models` endpoint if another switch is needed.
- **`/process` engine is live** — 3-phase pipeline: phase0 (parse → RequestContext with LLM decomposition, fuzzy supplier match), phase1 (deterministic filtering: category, geography, restricted, capacity, MOQ, budget, lead time), phase2 (score + rank). Output builder assembles final JSON with validation issues (V-xxx), escalations (ESC-xxx), uncertainties (U-xxx). Falls back to `example_output.json` on engine error.
- **`scripts/extract_request.py`** is also a standalone CLI: `python scripts/extract_request.py --request-text "..." --metadata-json '{}'`
- **Parser LLM params** — `temperature=0.1`, `max_tokens=2000` to reduce randomness and prevent JSON truncation.
- **Scenario tag definitions in prompt** — the parser prompt includes brief definitions for each tag (`standard`, `missing_info`, `contradictory`, `threshold`, `restricted`, `lead_time`, `capacity`, `multi_country`, `multilingual`) so the LLM can infer them from text.
- **No database** — all data is read from CSV/JSON files at request time.
- **`explainer.py`** lazy-initialises a single Groq client (module-level singleton). `max_tokens=1800`. Catches `groq.RateLimitError` and `groq.InternalServerError`. Prompt is concise (5 sections: Outcome, Top Recommendation, Alternatives, Excluded Suppliers, Escalations). `request_text` param removed — only takes `output_json`.
- **LLM field name drift** — the parser LLM sometimes outputs aliased field names (`budget` instead of `budget_amount`, `preferred_supplier` instead of `preferred_supplier_mentioned`, etc.). `_normalize_fields()` in `extract_request.py` remaps known aliases post-parse. Add new aliases there if new drift is observed. The parser prompt now puts the CRITICAL field names rule at the top of the rules list to reduce drift.
- **`preferred_supplier_mentioned`** must be a string (supplier name) or null — never a boolean. The LLM sometimes sets it to `true`; `_normalize_fields()` converts that to `null`. The prompt now explicitly states this rule twice (top of rules + inline).
- **Country normalisation** — `_normalize_fields()` maps full country names to ISO 3166-1 alpha-2 codes (e.g. `"Germany"` → `"DE"`) for both `country` and `delivery_countries`.
- **Chat trigger** — chat mode is only entered when a structural required field is missing (`quantity`, `category_l1`, `category_l2`, `delivery_countries`). Semantic issues (contradictions, implausible prices, past deadlines) are detected and returned but do NOT block the flow. This is enforced in `validate_request()`: `valid` is based on `struct_issues` only, not `sem_issues`.
- **Chatbot context injection** — the chatbot system prompt includes current request state (key field values) so the LLM knows what's already captured and can ask smarter questions. It also lists all field types including `preferred_supplier_mentioned`, `incumbent_supplier`, `unit_of_measure`, `esg_requirement`, `data_residency_constraint`.
- **Semantic validation types** — the LLM prompt allows `"type"` values: `"ambiguous"`, `"contradictory"`, `"invalid"`, `"implausible"` (expanded from just ambiguous/contradictory). Exceptions are logged via `logging.exception()` instead of silently swallowed.
- **Rate limit handling** — `/parse` catches `groq.RateLimitError` and returns HTTP 429 with a readable message instead of a 500. `explainer.py` also catches rate limit and internal server errors. `/results-chat` catches rate limits and `json_validate_failed` errors. Frontend retries once on 429 with a 3-second delay.
- **`/parse` response** — returns `{ request_json, field_provenance, inference_notes }`. In the frontend, `request_json` goes into `devData.parsed` and `{ field_provenance, inference_notes }` goes into `devData.provenance` (separate slot). Visible via the "Provenance / Notes" button in the dev panel. Not shown in the main UI.
- **`field_provenance` forwarded through chat** — the frontend stores `field_provenance` from `/parse`, sends it in `/chat` requests, and updates it from `updated_field_provenance` in chat responses. The dev panel provenance view stays up-to-date during chat.
- **Chat-first results** — after `/process`, results are presented via `/results-chat` as multi-message chat bubbles. The LLM agent has the full `output_json` as context and can answer follow-up questions. Escalation resolution happens inline — field_updates trigger silent `/process` rechecks.
- **`results_chat.py`** — system prompt uses `/no_think`, `max_tokens=2000`, `temperature=0.2`. Returns `{ messages: [...], updated_request_json, has_field_updates }`. Accepts both `messages` array and `reply` string from LLM. Merges `escalation_overrides` additively (doesn't replace existing overrides). Handles Groq `json_validate_failed` errors gracefully by extracting the `failed_generation` text from the error body and wrapping it as a valid response — this prevents crashes on casual follow-ups where the model emits plain text instead of JSON.
- **Escalation override map** — both `chatbot.py` (`_check_escalation_issues`) and `engine/output_builder.py` (`_apply_escalation_overrides`) use the same override keys: `threshold_exceeded` → ER-003, `restricted_supplier` → ER-002, `insufficient_quotes` → ER-004, `single_supplier_risk` → ER-006, `data_residency` → ER-005, `usd_compliance` → ER-008. New escalation rules must be added to both maps.
- **Chatbot max_tokens** raised to 800 (from 400) to accommodate detailed supplier comparisons in escalation resolution.
- **Post-chat policy recheck** — after each `/chat` turn in refinement mode, frontend silently calls `/process` to detect cascade effects (new/removed escalations from field updates). Visual indicator "Rechecking policy…" shown during recheck.
- **Frontend state** — `isResultsChat` flag controls whether `handleConvoSend` routes to `/results-chat` (results Q&A) or `/chat` (validation/escalation). Reset on "New Request".

### What Still Needs to Be Built
1. **Interactive chat components** — inline supplier cards, comparison tables, and escalation action buttons rendered in chat bubbles (planned next)
2. **Prompt suggestions** — clickable suggestion chips after initial results presentation (e.g. "Show alternatives", "Why was X excluded?")
3. **Historical context** — optionally use `historical_awards.csv` to inform rankings
4. **Stretch goals** — confidence scoring, ESG weighting, PDF export, approval routing

### Commit Conventions
- Never include "Co-Authored-By: Claude" or any AI authorship in commit messages
- Commit messages: short imperative subject line + bullet body for multi-change commits

## Git & GitHub workflow
- Shared team repository on GitHub
- **New feature → new branch**: always start from a fresh branch off `main`
- **Merging workflow** once a feature is working:
  1. `git checkout main && git pull origin main`
  2. `git merge <feature-branch>` — resolve any conflicts locally
  3. `git push origin main`
- **SSH passphrase**: Marco has an SSH key with a passphrase — the `git push` command will prompt for it; this is expected, just enter it when asked
- Never push directly to `main` without merging from an up-to-date local branch first
