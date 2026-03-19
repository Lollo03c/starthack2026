#!/usr/bin/env python3
"""Extract a procurement request JSON object from free text with Groq."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from groq import Groq


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_MODEL = "openai/gpt-oss-20b"


# Carica dal CSV le coppie categoria valide che il modello potra` usare.
def load_categories() -> list[dict[str, str]]:
    with (DATA_DIR / "categories.csv").open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# Estrae dai dati storici i valori ammessi per campi discreti come lingua, valuta e status.
def load_request_enums() -> dict[str, list[str]]:
    with (DATA_DIR / "requests.json").open(encoding="utf-8") as fh:
        rows = json.load(fh)

    def unique_values(field: str) -> list[str]:
        return sorted({row[field] for row in rows if row.get(field) is not None})

    scenario_tags = sorted(
        {tag for row in rows for tag in row.get("scenario_tags", []) if tag is not None}
    )

    return {
        "request_channel": unique_values("request_channel"),
        "request_language": unique_values("request_language"),
        "currency": unique_values("currency"),
        "contract_type_requested": unique_values("contract_type_requested"),
        "status": unique_values("status"),
        "scenario_tags": scenario_tags,
    }


# Permette a un campo dello schema JSON di accettare anche il valore null.
def nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


# Costruisce lo schema JSON completo che la risposta del modello deve rispettare.
def build_schema(enums: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "request_id": {"type": "string"},
            "created_at": {"type": "string"},
            "request_channel": {"type": "string", "enum": enums["request_channel"]},
            "request_language": {"type": "string", "enum": enums["request_language"]},
            "business_unit": {"type": "string"},
            "country": {"type": "string"},
            "site": nullable({"type": "string"}),
            "requester_id": nullable({"type": "string"}),
            "requester_role": nullable({"type": "string"}),
            "submitted_for_id": nullable({"type": "string"}),
            "category_l1": {
                "type": "string",
                "enum": sorted({"IT", "Facilities", "Professional Services", "Marketing"}),
            },
            "category_l2": {"type": "string"},
            "title": {"type": "string"},
            "request_text": {"type": "string"},
            "currency": {"type": "string", "enum": enums["currency"]},
            "budget_amount": nullable({"type": "number"}),
            "quantity": nullable({"type": "number"}),
            "unit_of_measure": nullable({"type": "string"}),
            "required_by_date": nullable({"type": "string"}),
            "preferred_supplier_mentioned": nullable({"type": "string"}),
            "incumbent_supplier": nullable({"type": "string"}),
            "contract_type_requested": {
                "type": "string",
                "enum": enums["contract_type_requested"],
            },
            "delivery_countries": {
                "type": "array",
                "items": {"type": "string"},
            },
            "data_residency_constraint": {"type": "boolean"},
            "esg_requirement": {"type": "boolean"},
            "status": {"type": "string", "enum": enums["status"]},
            "scenario_tags": {
                "type": "array",
                "items": {"type": "string", "enum": enums["scenario_tags"]},
            },
        },
        "required": [
            "request_id",
            "created_at",
            "request_channel",
            "request_language",
            "business_unit",
            "country",
            "site",
            "requester_id",
            "requester_role",
            "submitted_for_id",
            "category_l1",
            "category_l2",
            "title",
            "request_text",
            "currency",
            "budget_amount",
            "quantity",
            "unit_of_measure",
            "required_by_date",
            "preferred_supplier_mentioned",
            "incumbent_supplier",
            "contract_type_requested",
            "delivery_countries",
            "data_residency_constraint",
            "esg_requirement",
            "status",
            "scenario_tags",
        ],
    }


# Converte le categorie in un blocco testuale leggibile da inserire nel prompt.
def build_category_reference(categories: list[dict[str, str]]) -> str:
    lines = []
    for row in categories:
        lines.append(
            f'- {row["category_l1"]} / {row["category_l2"]} '
            f'(unit: {row["typical_unit"]}, pricing_model: {row["pricing_model"]})'
        )
    return "\n".join(lines)


# Crea il prompt con regole, metadata e lista categorie per guidare l'estrazione.
def build_prompt(
    request_text: str,
    metadata: dict[str, Any],
    categories: list[dict[str, str]],
    enums: dict[str, list[str]],
) -> str:
    category_reference = build_category_reference(categories)
    metadata_json = json.dumps(metadata, ensure_ascii=False, indent=2)

    return f"""
You extract procurement requests into the target JSON structure used by this dataset.

Rules:
- Return one JSON object only.
- Keep metadata values exactly as provided when they are already present.
- Do not invent requester IDs or site names. If not provided in metadata, use null for nullable fields.
- If quantity, budget, required date, supplier preference, or incumbent are missing, use null.
- Infer request_language from the text if missing in metadata.
- Infer category_l1 and category_l2 by choosing the best matching pair from the allowed list below.
- Infer unit_of_measure from the request text and category reference.
- Generate a short neutral title in English.
- Preserve the original request text verbatim in request_text.
- Use ISO 8601 for created_at and YYYY-MM-DD for required_by_date.
- Use only these request_channel values: {", ".join(enums["request_channel"])}
- Use only these languages: {", ".join(enums["request_language"])}
- Use only these currencies: {", ".join(enums["currency"])}
- Use only these contract_type_requested values: {", ".join(enums["contract_type_requested"])}
- Use only these scenario tags when relevant: {", ".join(enums["scenario_tags"])}
- If the text is missing key information such as quantity, budget, or specification, include "missing_info".
- If the text contains conflicting or internally inconsistent details, include "contradictory".
- If the text names a supplier explicitly, set preferred_supplier_mentioned to that supplier name.
- Default status to "new" unless metadata explicitly provides another value.
- delivery_countries should default to [country] when not otherwise specified and country is known.
- data_residency_constraint and esg_requirement default to false unless the text or metadata clearly indicates true.

Allowed category pairs:
{category_reference}

Metadata:
{metadata_json}

Free-text request:
{request_text}
""".strip()


# Definisce gli argomenti accettati da terminale quando lanci lo script.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-text", help="Free-text procurement request.")
    parser.add_argument(
        "--request-text-file",
        help="Path to a UTF-8 text file containing the free-text procurement request.",
    )
    parser.add_argument(
        "--metadata-json",
        default="{}",
        help="Inline JSON object with known metadata fields.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Groq model to use. Default: {DEFAULT_MODEL}",
    )
    return parser.parse_args()


# Carica il testo della richiesta da argomento diretto oppure da file.
def load_request_text(args: argparse.Namespace) -> str:
    if bool(args.request_text) == bool(args.request_text_file):
        raise SystemExit("Provide exactly one of --request-text or --request-text-file.")
    if args.request_text:
        return args.request_text.strip()
    return Path(args.request_text_file).read_text(encoding="utf-8").strip()


# Completa i metadata mancanti con default ragionevoli prima di chiamare il modello.
def build_default_metadata(raw_metadata: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(raw_metadata)
    metadata.setdefault("request_id", "REQ-LOCAL-000001")
    metadata.setdefault(
        "created_at",
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    metadata.setdefault("request_channel", "portal")
    metadata.setdefault("request_language", None)
    metadata.setdefault("business_unit", "Unknown")
    metadata.setdefault("country", "Unknown")
    metadata.setdefault("site", None)
    metadata.setdefault("requester_id", None)
    metadata.setdefault("requester_role", None)
    metadata.setdefault("submitted_for_id", None)
    metadata.setdefault("incumbent_supplier", None)
    metadata.setdefault("contract_type_requested", "purchase")
    metadata.setdefault("delivery_countries", None)
    metadata.setdefault("data_residency_constraint", None)
    metadata.setdefault("esg_requirement", None)
    metadata.setdefault("status", "new")
    return metadata


# Invia prompt e schema a Groq e converte la risposta JSON del modello in un dict Python.
def extract_request(
    client: Groq,
    model: str,
    request_text: str,
    metadata: dict[str, Any],
    categories: list[dict[str, str]],
    enums: dict[str, list[str]],
) -> dict[str, Any]:
    schema = build_schema(enums)
    prompt = build_prompt(request_text, metadata, categories, enums)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a careful procurement data extraction assistant.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "procurement_request",
                "strict": True,
                "schema": schema,
            },
        },
    )

    return json.loads(response.choices[0].message.content)


# Coordina tutto il flusso: legge input, prepara metadata, chiama Groq e stampa il JSON finale.
def main() -> None:
    args = parse_args()
    request_text = load_request_text(args)

    try:
        raw_metadata = json.loads(args.metadata_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid --metadata-json: {exc}") from exc

    metadata = build_default_metadata(raw_metadata)
    categories = load_categories()
    enums = load_request_enums()

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise SystemExit("Set GROQ_API_KEY before running this script.")

    client = Groq(api_key=api_key)
    payload = extract_request(client, args.model, request_text, metadata, categories, enums)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
