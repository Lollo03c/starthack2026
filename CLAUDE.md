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
| `client_simulator.py` | `simulate_client_response(escalation_rule, trigger, request_json, output_json)` — Groq-based client response simulation for "Ask the Client" escalation buttons |
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
| `POST` | `/simulate-client` | `{ escalation_rule, escalation_trigger, request_json, output_json }` → `{ message, field_updates }` — simulates cooperative client response for escalation resolution |
| `POST` | `/simulate-client-validation` | `{ field, question, request_json }` → `{ message, field_updates }` — simulates client providing a missing field value during validation |
| `POST` | `/results-chat` | `{ messages, output_json, request_json }` → `{ messages: [...], updated_request_json, has_field_updates }` — presents results in chat, handles Q&A + escalation resolution |

### Procurement Professional Framing
- The user is a **procurement professional** processing a client's purchase request — NOT the person making the purchase
- All copy, prompts, and LLM system instructions reflect this: "Paste a purchase request", "PO issued to", "Ask the Client", etc.
- `results_chat.py` and `chatbot.py` system prompts explicitly state the user is the procurement agent, not the requester
- Forward button reads "Approve & Create PO →", success screen reads "Purchase Order Created"

### UI Flow (Single-Window Chat + Sidebar + Dashboard Toggle)
1. Initial state: sidebar (260px left column, always visible) + full-viewport centered hero (brand, headline, subtext) with chat input bar below hero in normal document flow
2. Submit (Enter or arrow button) → hero fades out (CSS transition), user message shows as chat bubble, typing indicator appears. Top bar is always visible (ChatGPT-style: "New chat" icon+text on left, "ChainIQ Sourcing" title on right)
3. Pipeline: `POST /parse` → `POST /validate` → (if invalid: clarification appears in same chat — no phase switch) → auto-proceed when resolved → `POST /process` → `POST /results-chat`
4. **Results in chat**: LLM summary messages appear as chat bubbles + **"Open Dashboard"** button + suggestion chips + forward button
5. **Dashboard panel** (`#dashboard-panel`): toggleable left panel titled "Request Summary" with structured output (actions required with action buttons, current choice, supplier comparison table, supplier preference, alternatives, excluded). No status banner. Toggled via "Open Dashboard" button in chat or "Show/Hide Dashboard" button in top bar
6. After escalation resolution via chat or action buttons, silent `/process` recheck updates dashboard content via `refreshOutputPanel()`
7. "New chat" button in top bar calls `createNewConversation()` — auto-saves current state, resets UI, creates new conversation ID
8. Dev panel (bottom-right corner, only visible at `?dev=true`): three buttons open dark modals — Parsed JSON, Output JSON, Provenance / Notes
9. Responsive: below 1024px, dashboard becomes full-screen overlay (fixed, z-30) instead of side panel, sidebar hidden
10. **Single container architecture**: one `#messages` div, one `#chat-input` bar, one set of event listeners — no message migration between containers
11. Old results page (`result-phase`) code remains but is unused in current flow

### Chat History Sidebar
- **`#sidebar`**: 260px fixed-width left column, always visible on desktop, hidden on mobile (<1024px)
- **localStorage persistence**: conversations stored in `localStorage('cq_conversations')` as JSON array
- **Conversation data model**: `{ id, title, status, created_at, updated_at, messages, requestJson, outputJson, fieldProvenance, inferenceNotes, originalRequestText, explicitShipSupplierName, activeRankingMetric, isResultsChat, currentSupplierShortlist }`
- **`status`**: `"active"` or `"completed"` (set to completed on PO creation via `showForwardScreen()`)
- **`title`**: first 60 chars of `originalRequestText`, fallback "New Request"
- **Key functions**: `saveConversation(conv)`, `loadConversations()`, `deleteConversation(id)`, `autoSaveCurrentState()`, `renderSidebar()`, `loadConversation(id)`, `createNewConversation()`
- **Auto-save triggers**: after parse, validate, process, chat turn, results-chat turn, escalation resolution (client sim or internal approval), PO creation
- **Cap**: 50 conversations max, oldest completed pruned first
- **Loading a completed conversation**: input is disabled, placeholder says "This request has been completed."

### Escalation Action Buttons
- **Client escalations** (`CLIENT_ESCALATIONS` set: ER-001, ER-009, ER-010, ER-011): "Ask the Client" button (blue outline) → calls `POST /simulate-client` → shows client response in distinct bubble style (light blue bg, "Client" label, person icon) → merges field_updates → silent reprocess
- **Internal escalations** (`INTERNAL_ESCALATIONS` map: ER-002 through ER-008): "Request Approval from [Role]" button (gray outline) → simulated delay (1.5-2.5s) → green approval notification pill → sets escalation_overrides → silent reprocess
- **`client_simulator.py`**: Groq `qwen/qwen3-32b`, `/no_think`, `temperature=0.3`, `max_tokens=500`. System prompt simulates cooperative stakeholder. Per-rule hints guide LLM responses.
- **First message is client-styled** — the initial purchase request appears as a centered `msg-client` bubble (light blue, "Client" label) rather than a right-aligned user bubble. Input bar starts with `.client-input` class (blue border, light blue bg, "Client" tag). After submit, input bar reverts to normal white styling.
- **Validation missing fields via "Ask the Client"** — when `/validate` returns missing required fields, the AI shows each question with an "Ask the Client" button. Clicking calls `POST /simulate-client-validation` → client response appears in `msg-client` bubble → field_updates merged → next question shown or auto-proceed to `/process`. Manual typing fallback still works via existing `/chat` flow.
- **`client_simulator.py` `simulate_client_field_response()`** — new function for validation field collection. Per-field hints for quantity, category_l1, category_l2, delivery_countries. Same Groq client/model as escalation simulator.
- **New message types**: `msg-client` (light blue bg, blue left border, "Client" label), `msg-system-notification` (centered pill, neutral=gray or success=green)
- **`ESCALATION_OVERRIDE_KEYS`** map: mirrors `results_chat.py` override key mapping for internal approval resolution

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
- **Frontend state** — `isResultsChat` flag controls whether `handleConvoSend` routes to `/results-chat` (results Q&A) or `/chat` (validation/escalation). Reset on "New Request". `dashboardReady` tracks whether dashboard content has been populated. `isDashboardVisible` tracks toggle state.
- **Single-window layout** — unified `#app` container with `#dashboard-panel` (flex sibling, hidden initially) and `#chat-area` (hero + messages + input). No more `#chat-phase`, `#convo-phase`, `#split-phase`, or `#loading-overlay`. Single `#messages` container, single `#chat-input` bar, single set of event listeners. `getActiveMessageContainer()` / `getActiveInput()` / etc. now simply return the single element.
- **Chat input bar** — in hero state, `#chat-input-bar` is in normal document flow below the hero content (flexbox child of `#chat-area`), so it grows upward naturally without overlapping hero text. On submit, `activateChatMode()` adds `.chat-mode` class which switches to `position: absolute; bottom: 1rem` (pinned at bottom). Inner `.input-pill` div provides the ChatGPT-style pill look (white bg, `border-radius: 1.5rem`, shadow). Textarea max-height is 200px. `#messages` has `pb-24` to clear the floating bar. `resetToInitial()` removes `.chat-mode` to return bar to normal flow.
- **Top bar** — always visible (never hidden/shown on state change). Left: pen icon + "New chat" (`resetToInitial()`). Right: "ChainIQ Sourcing" title. No border, clean white background.
- **Chat bubble styles** — user messages: light gray bg (`#f0f0f0`), uniform `border-radius: 1.25rem`, dark text. AI messages: transparent background, no border, just dark text — ChatGPT-style.
- **Dashboard toggle** — `toggleDashboard(forceShow)` swaps `.dashboard-hidden` / `.dashboard-visible` CSS classes on `#dashboard-panel`. `.dashboard-hidden` uses `width: 0; overflow: hidden` with CSS transitions. `.dashboard-visible` uses `width: 50%`. On mobile (< 1024px), dashboard becomes a fixed full-screen overlay. Top bar has "Show/Hide Dashboard" button (hidden until results ready). "Open Dashboard" button also inserted into chat messages after results. Gray circular reopen button (`#dashboard-reopen-btn`) stays hidden until the dashboard has been opened at least once (`dashboardUnlocked` is set in `toggleDashboard` on first open, not when the chat button is rendered). CSS uses `#dashboard-reopen-btn:not(.hidden) { display: flex }` to avoid specificity conflicts with Tailwind's `.hidden`.
- **Auto-proceed on resolution** — when `/chat` returns `resolved: true`, frontend automatically appends "We have everything we need" message and calls `proceedToProcess()`. No submit button needed.
- **Dashboard "Request Summary"** — `refreshOutputPanel()` renders in this order: (1) title "Request Summary", (2) Actions Required (escalations, only if any), (3) Current Choice, (4) Supplier Comparison table (always visible), (5) Supplier Preference (if applicable), (6) Alternative Suppliers (expandable `<details>`), (7) Excluded Suppliers (expandable `<details>`). No status banner. Old `buildStatusBannerHtml()`, `renderEscalationsPanelHtml()`, `buildRequestDetailsHtml()` removed.
- **Actions Required** — `renderActionsRequiredHtml()` replaces escalation cards. Uses red left-border bar style for blocking items, grey for optional. Human-readable titles from `ESCALATION_TITLES` map, resolution hints from `ESCALATION_HELP` map. No escalation IDs or rule IDs shown.
- **Current Choice** — `renderCurrentChoiceHtml()` replaces `renderTopRecommendationVisual()`. Shows supplier name, fit rationale, total/unit price, lead time, service regions, capacity. No scores, no tags (preferred/incumbent/compliant pills removed). Preserves `getCanonicalShipSupplier()` pinning logic.
- **Supplier Comparison table** — always visible (no toggle), columns: rank, supplier, total price, lead time, quality, risk, ESG. `isRankingPanelOpen` state removed. Metric switcher (overall/cheaper/fastest/lowest_risk) still present.
- **Supplier Preference** — `renderSupplierPreferenceHtml()` replaces `renderMandatedSupplierVisual()`. Grey left-border bar style (`border-l-4 border-gray-400`). Skipped on conflict (escalation handles it).
- **Alternative Suppliers** — `renderAlternativeCardsHtml()` replaces `renderAlternativesVisual()`. Expandable `<details>` with count badge. Individual cards with name, rank, price delta vs current choice, lead time, tradeoff text. No raw scores.
- **Excluded Suppliers** — `renderExcludedCardsHtml()` replaces `renderExcludedVisual()`. Same card style as alternatives. Colored constraint tags from `EXCLUSION_LABELS` map (Geography, Restricted, Capacity, etc.) derived from `eliminated_at` stage or reason text fallback.
- **JS lookup maps** — `ESCALATION_TITLES` (rule ID → human title), `ESCALATION_HELP` (rule ID → resolution guidance), `EXCLUSION_LABELS` (`eliminated_at` stage → `{ label, color }` tag config).
- **Supplier output enriched** — `_format_scored()` in `output_builder.py` now includes `service_regions` and `capacity_per_month` fields.
- **LLM prompt (results_chat.py)** — chat never mentions escalation IDs, rule IDs, or raw scores. Uses human-readable titles for escalations, constraint category names for excluded suppliers. Cites prices/dates/lead times instead of scores.
- **Escalation approval heuristics** — `_apply_resolution_heuristics()` in `results_chat.py` catches both specific phrases ("approved by head of category") and general approval language ("I have all approval", "approval confirmed", "acknowledged", "approved", etc.) to set `threshold_exceeded` / `insufficient_quotes` overrides for ER-003 / ER-004. Needed because the LLM sometimes returns the budget field update but omits the escalation override for ER-004.
- **Ranking metrics** — `RANKING_METRICS` object defines four sort modes: `overall` (composite score), `cheaper` (lowest price), `fastest` (shortest lead time), `lowest_risk` (lowest risk score). `getRankedShortlistForMetric()` re-sorts the shortlist. `syncActiveShortlist()` updates `currentSupplierShortlist` when metric changes. `renderRankingSwitcher()` renders metric toggle buttons above the comparison table. `getActiveRankedOutput()` decorates output with `ui_ranked_shortlist`, `ui_top_supplier`, `ui_official_top_supplier`, `ui_metric_meta`.
- **Current Choice pinned to ship supplier** — `renderCurrentChoiceHtml()` always shows `getCanonicalShipSupplier()` as the hero card, not the metric-sorted #1. Changing the ranking metric only re-sorts the comparison table and alternatives — the hero card stays pinned. The supplier only changes if the user explicitly requests it via chat (which sets `explicitShipSupplierName`).
- **`getCanonicalShipSupplier()`** — returns the supplier to ship with, in priority order: (1) mandated supplier if `supplier_must_use`, (2) `explicitShipSupplierName` if user switched via chat, (3) engine's overall #1 from `recommendation.recommended_supplier_name`, (4) first in shortlist.
- **`ship_supplier_selection`** — `results_chat.py` `_apply_resolution_heuristics()` returns a third value `ship_supplier_selection` dict when the user explicitly asks to switch supplier. Frontend stores `ship_supplier_selection.supplier_name` in `explicitShipSupplierName`.

### What Still Needs to Be Built
1. **Historical context** — optionally use `historical_awards.csv` to inform rankings
2. **Stretch goals** — confidence scoring, ESG weighting, PDF export, approval routing

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
