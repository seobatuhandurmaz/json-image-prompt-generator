import os, io, base64, json
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from .schemas import FormDataIn, PromptOut
from .prompt_builder import build_prompt
from PIL import Image

API_KEY = os.getenv("APP_API_KEY", "")       # boş bırakabilirsin (WP'de header yok)
ALLOW_ORIGINS = os.getenv("ALLOW_ORIGINS", "*").split(",")
WP_ORIGIN = os.getenv("WP_ORIGIN", "")       # örn: https://www.siteniz.com

app = FastAPI(title="Jengal Prompt API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _require_auth(x_api_key: str | None):
    if API_KEY and (x_api_key or "") != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

def _check_referer(referer: str | None):
    if not WP_ORIGIN:
        return
    if not referer:
        raise HTTPException(status_code=403, detail="Missing Referer")
    if urlparse(referer).netloc != urlparse(WP_ORIGIN).netloc:
        raise HTTPException(status_code=403, detail="Bad Referer")

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/generate", response_model=PromptOut)
async def generate_prompt(
    request: Request,
    x_api_key: str | None = None,
    json_data: str = Form(None),
    reference_image: UploadFile | None = File(None)
):
    _require_auth(x_api_key)
    _check_referer(request.headers.get("referer"))
    if not json_data:
        raise HTTPException(status_code=400, detail="json_data (Form field) gerekli")
    try:
        payload = FormDataIn.model_validate_json(json_data)
    except ValidationError as ve:
        raise HTTPException(status_code=422, detail=ve.errors())

    ref_url = None
    if reference_image:
        buf = await reference_image.read()
        try:
            Image.open(io.BytesIO(buf))
        except Exception:
            pass
        b64 = base64.b64encode(buf).decode("utf-8")
        ref_url = f"data:{reference_image.content_type};base64,{b64}"

    prompt = build_prompt(payload, reference_image_url=ref_url)
    return {"prompt": prompt}

@app.post("/generate-json", response_model=PromptOut)
async def generate_prompt_json(payload: FormDataIn, request: Request, x_api_key: str | None = None):
    _require_auth(x_api_key)
    _check_referer(request.headers.get("referer"))
    prompt = build_prompt(payload, reference_image_url=payload.referenceImageBase64)
    return {"prompt": prompt}
