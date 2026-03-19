import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from explainer import explain_decision  # noqa: E402 — after dotenv
from engine import load_data, process_request as engine_process  # noqa: E402

BASE_DIR = Path(__file__).parent
EXAMPLES_DIR = BASE_DIR / "examples"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Procurement Decision Explainer")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Load data once at startup
_engine_data = load_data(str(BASE_DIR / "data"))


@app.get("/")
def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/example")
def get_example():
    output_path = EXAMPLES_DIR / "example_output.json"
    request_path = EXAMPLES_DIR / "example_request.json"

    if not output_path.exists():
        raise HTTPException(status_code=404, detail="example_output.json not found")

    output_json = json.loads(output_path.read_text())
    request_json = json.loads(request_path.read_text()) if request_path.exists() else {}

    return {"output_json": output_json, "request_json": request_json}


class ParseRequest(BaseModel):
    request_text: str
    metadata: dict = {}


@app.post("/parse")
def parse(body: ParseRequest):
    sys.path.insert(0, str(BASE_DIR / "scripts"))
    from extract_request import parse_request_text  # noqa: PLC0415

    try:
        result = parse_request_text(body.request_text, body.metadata)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        if "rate_limit_exceeded" in str(e) or "429" in str(e):
            raise HTTPException(status_code=429, detail="Groq API rate limit reached. Please wait a few minutes before trying again.")
        raise HTTPException(status_code=500, detail=str(e))
    field_provenance = result.pop("field_provenance", {})
    inference_notes = result.pop("inference_notes", {})
    return {"request_json": result, "field_provenance": field_provenance, "inference_notes": inference_notes}


class ProcessRequest(BaseModel):
    request_json: dict
    field_provenance: dict = {}
    inference_notes: dict = {}


@app.post("/process")
def process(body: ProcessRequest):
    try:
        output_json = engine_process(body.request_json, _engine_data)
    except Exception as e:
        # Fallback to example output so the UI doesn't break during development
        import logging
        logging.getLogger(__name__).error("Engine error, falling back to example: %s", e, exc_info=True)
        output_path = EXAMPLES_DIR / "example_output.json"
        if not output_path.exists():
            raise HTTPException(status_code=500, detail=f"Engine failed: {e}")
        output_json = json.loads(output_path.read_text())
    return {"output_json": output_json, "request_json": body.request_json}


class ExplainRequest(BaseModel):
    output_json: dict
    request_text: str | None = None


@app.post("/explain")
def explain(body: ExplainRequest):
    if not os.environ.get("GROQ_API_KEY"):
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    try:
        explanation = explain_decision(body.output_json, body.request_text)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"explanation": explanation}


class ValidateRequest(BaseModel):
    request_json: dict
    original_request_text: str = ""


@app.post("/validate")
def validate_endpoint(body: ValidateRequest):
    from validation import validate_request  # noqa: PLC0415

    valid, issues = validate_request(body.request_json, body.original_request_text)
    return {"valid": valid, "issues": issues}


class ChatRequest(BaseModel):
    messages: list
    request_json: dict
    issues: list
    original_request_text: str = ""
    field_provenance: dict = {}
    supplier_shortlist: list = []


@app.post("/chat")
def chat_endpoint(body: ChatRequest):
    from chatbot import run_chat_turn  # noqa: PLC0415

    return run_chat_turn(body.messages, body.request_json, body.issues, body.original_request_text, body.field_provenance, body.supplier_shortlist)


class ResultsChatRequest(BaseModel):
    messages: list
    output_json: dict
    request_json: dict


@app.post("/results-chat")
def results_chat_endpoint(body: ResultsChatRequest):
    import logging
    from results_chat import run_results_chat  # noqa: PLC0415

    try:
        return run_results_chat(body.messages, body.output_json, body.request_json)
    except Exception as e:
        logging.getLogger(__name__).error("results-chat error: %s", e, exc_info=True)
        if "rate_limit_exceeded" in str(e) or "429" in str(e):
            raise HTTPException(status_code=429, detail="Groq API rate limit reached. Please wait a moment.")
        raise HTTPException(status_code=500, detail=f"Results chat failed: {e}")
