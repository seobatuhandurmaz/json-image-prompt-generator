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
    Header,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from PIL import Image

from .schemas import FormDataIn, PromptOut
from .prompt_builder import build_prompt

# =========================
# Environment / Config
# =========================
API_KEY = (os.getenv("APP_API_KEY", "") or "").strip()  # boşsa auth kapalı
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
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Guards
# =========================
def _require_auth(x_api_key: str | None):
    """
    Eğer APP_API_KEY set edildiyse, başlıktan birebir eşleşme ister.
    Set edilmemişse (""), kimlik doğrulama devre dışı kalır.
    """
    if not API_KEY:
        return
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    if x_api_key.strip() != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


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
    # Header'dan oku (X-API-Key). alias ile ismi açıkça belirtiyoruz.
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    # multipart form alanları
    json_data: str = Form(None),
    reference_image: UploadFile | None = File(None),
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
        # Görseli okuyup data URL'e çeviriyoruz (base64). Böylece uzun URL hatası olmaz.
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
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    _require_auth(x_api_key)
    _check_referer(request.headers.get("referer"))

    prompt = build_prompt(payload, reference_image_url=payload.referenceImageBase64)
    return {"prompt": prompt}
