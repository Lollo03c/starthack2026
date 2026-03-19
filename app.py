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

BASE_DIR = Path(__file__).parent
EXAMPLES_DIR = BASE_DIR / "examples"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Procurement Decision Explainer")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
    return {"request_json": result}


class ProcessRequest(BaseModel):
    request_json: dict


@app.post("/process")
def process(body: ProcessRequest):
    output_path = EXAMPLES_DIR / "example_output.json"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="example_output.json not found")
    output_json = json.loads(output_path.read_text())
    return {"output_json": output_json, "request_json": body.request_json}


class ExplainRequest(BaseModel):
    output_json: dict
    request_text: str | None = None


@app.post("/explain")
def explain(body: ExplainRequest):
    if not os.environ.get("GROQ_API_KEY"):
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    explanation = explain_decision(body.output_json, body.request_text)
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


@app.post("/chat")
def chat_endpoint(body: ChatRequest):
    from chatbot import run_chat_turn  # noqa: PLC0415

    return run_chat_turn(body.messages, body.request_json, body.issues, body.original_request_text)
