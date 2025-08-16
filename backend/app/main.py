# backend/app/main.py

import os
import io
import base64
from urllib.parse import urlparse

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    Request,
    HTTPException,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from PIL import Image

from .schemas import FormDataIn, PromptOut
from .prompt_builder import build_prompt

# =========================
# Environment / Config
# =========================
# Not: APP_API_KEY artık istemciden beklenmiyor; burada kullanılmıyor.
ALLOW_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.getenv("ALLOW_ORIGINS", "*").split(",")
    if o.strip()
]
WP_ORIGIN = (os.getenv("WP_ORIGIN", "") or "").rstrip("/")

# =========================
# App & Middlewares
# =========================
app = FastAPI(title="Image Prompt API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# =========================
# Guards
# =========================
def _check_referer(referer: str | None):
    """
    WP_ORIGIN verilmişse, gelen isteğin Referer origin’i aynı olmalı.
    Boşsa kontrol devre dışı.
    """
    if not WP_ORIGIN:
        return
    if not referer:
        raise HTTPException(status_code=403, detail="Missing Referer")
    if urlparse(referer).netloc != urlparse(WP_ORIGIN).netloc:
        raise HTTPException(status_code=403, detail="Bad Referer")

# =========================
# Endpoints
# =========================
@app.get("/health")
def health():
    return {"ok": True}

@app.post("/generate", response_model=PromptOut)
async def generate_prompt(
    request: Request,
    json_data: str = Form(None),
    reference_image: UploadFile | None = File(None),
):
    # Sadece referer/domain kontrolü
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
        # Basit görsel doğrulaması (opsiyonel)
        try:
            Image.open(io.BytesIO(buf))
        except Exception:
            pass
        b64 = base64.b64encode(buf).decode("utf-8")
        mime = reference_image.content_type or "image/png"
        ref_url = f"data:{mime};base64,{b64}"

    prompt = build_prompt(payload, reference_image_url=ref_url)
    return {"prompt": prompt}

@app.post("/generate-json", response_model=PromptOut)
async def generate_prompt_json(
    payload: FormDataIn,
    request: Request,
):
    # Sadece referer/domain kontrolü
    _check_referer(request.headers.get("referer"))

    prompt = build_prompt(payload, reference_image_url=payload.referenceImageBase64)
    return {"prompt": prompt}
