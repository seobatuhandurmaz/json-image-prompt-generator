import os
import io
import base64
import hashlib
import asyncio
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timedelta

from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from PIL import Image

from .schemas import FormDataIn, PromptOut
from .prompt_builder import build_prompt

# =========================
# Config (ENV)
# =========================
ALLOW_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.getenv("ALLOW_ORIGINS", "*").split(",")
    if o.strip()
]
WP_ORIGIN = (os.getenv("WP_ORIGIN", "") or "").rstrip("/")

# Referans görseller için geçici dizin
REF_DIR = Path(os.getenv("REF_DIR", "/tmp/refs"))
REF_DIR.mkdir(parents=True, exist_ok=True)

# Görsel işleme ve temizlik limitleri
MAX_REF_SIDE = int(os.getenv("MAX_REF_SIDE", "1600"))          # px
REF_TTL_HOURS = int(os.getenv("REF_TTL_HOURS", "24"))          # saat
MAX_REF_STORAGE_MB = int(os.getenv("MAX_REF_STORAGE_MB", "500"))  # MB
CLEAN_INTERVAL_MIN = int(os.getenv("CLEAN_INTERVAL_MIN", "30"))   # dakika

# =========================
# App
# =========================
app = FastAPI(title="Image Prompt API", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# /refs altında statik dosya servis et
app.mount("/refs", StaticFiles(directory=str(REF_DIR)), name="refs")

# =========================
# Helpers
# =========================
def _check_referer(referer: str | None):
    """WP_ORIGIN verilmişse, gelen isteğin Referer origin’i aynı olmalı."""
    if not WP_ORIGIN:
        return
    if not referer:
        raise HTTPException(status_code=403, detail="Missing Referer")
    if urlparse(referer).netloc != urlparse(WP_ORIGIN).netloc:
        raise HTTPException(status_code=403, detail="Bad Referer")

def _guess_ext(content_type: str | None, fallback: str = "png") -> str:
    m = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    return m.get((content_type or "").lower(), fallback)

def _maybe_downscale(buf: bytes, content_type: str | None) -> bytes:
    """Büyük görselleri MAX_REF_SIDE sınırına indir, kaliteyi koru."""
    try:
        im = Image.open(io.BytesIO(buf))
        # doğrula ve yeniden aç (Pillow önerisi)
        im.verify()
        im = Image.open(io.BytesIO(buf))

        if max(im.size) <= MAX_REF_SIDE:
            return buf

        # saydamlık vb. için güvenli dönüşüm
        if im.mode in ("P", "RGBA"):
            im = im.convert("RGB")

        im.thumbnail((MAX_REF_SIDE, MAX_REF_SIDE))  # in-place küçültme

        out = io.BytesIO()
        ext = _guess_ext(content_type)
        if ext in ("jpg", "jpeg"):
            im.save(out, format="JPEG", quality=85, optimize=True)
        elif ext == "webp":
            im.save(out, format="WEBP", quality=85, method=6)
        else:
            im.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return buf  # sorun olursa orijinali döndür

def _public_base(request: Request) -> str:
    """Railway proxy arkasında doğru public base URL'yi üret."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"

def _file_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except FileNotFoundError:
        return 0.0

def _dir_size_bytes(d: Path) -> int:
    total = 0
    for p in d.glob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except FileNotFoundError:
                pass
    return total

def _cleanup_ttl():
    """TTL süresi dolan dosyaları sil."""
    if REF_TTL_HOURS <= 0:
        return
    cutoff = datetime.utcnow() - timedelta(hours=REF_TTL_HOURS)
    for p in REF_DIR.glob("*"):
        try:
            if datetime.utcfromtimestamp(_file_mtime(p)) < cutoff:
                p.unlink(missing_ok=True)
        except Exception:
            pass

def _enforce_quota():
    """Toplam boyut kotasını uygula (en eskileri sil)."""
    if MAX_REF_STORAGE_MB <= 0:
        return
    limit = MAX_REF_STORAGE_MB * 1024 * 1024
    size = _dir_size_bytes(REF_DIR)
    if size <= limit:
        return
    files = sorted(
        [p for p in REF_DIR.glob("*") if p.is_file()],
        key=_file_mtime
    )
    for p in files:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
        size = _dir_size_bytes(REF_DIR)
        if size <= limit:
            break

async def _janitor_loop():
    """Periyodik temizlik: TTL + kota."""
    while True:
        try:
            _cleanup_ttl()
            _enforce_quota()
        finally:
            await asyncio.sleep(max(CLEAN_INTERVAL_MIN, 1) * 60)

@app.on_event("startup")
async def _startup():
    _cleanup_ttl()
    _enforce_quota()
    asyncio.create_task(_janitor_loop())

async def _save_ref_and_get_url(upload: UploadFile, request: Request) -> str:
    """Yüklenen görseli kaydet ve /refs/<id>.<ext> kısa URL döndür."""
    buf = await upload.read()
    buf = _maybe_downscale(buf, upload.content_type)

    digest = hashlib.sha256(buf).hexdigest()[:16]
    ext = _guess_ext(upload.content_type)
    fname = f"{digest}.{ext}"
    fpath = REF_DIR / fname

    # dedup: aynı içerik varsa yeniden yazma
    if not fpath.exists():
        fpath.write_bytes(buf)

    # her kayıtta temizlik/kota kontrolü
    _cleanup_ttl()
    _enforce_quota()

    base = _public_base(request).rstrip("/")
    return f"{base}/refs/{fname}"

def _parse_data_url(b64_or_dataurl: str) -> tuple[bytes, str]:
    """
    'data:<mime>;base64,<data>' ya da düz base64 alır, (bytes, mime) döndürür.
    """
    s = (b64_or_dataurl or "").strip()
    if s.startswith("data:"):
        try:
            header, data = s.split(",", 1)
            mime = header.split(";")[0][5:] or "image/png"
            return base64.b64decode(data), mime
        except Exception:
            pass
    # düz base64 kabul et
    try:
        return base64.b64decode(s), "image/png"
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 reference image")

async def _save_base64_and_get_url(b64_or_dataurl: str, request: Request) -> str:
    buf, mime = _parse_data_url(b64_or_dataurl)
    buf = _maybe_downscale(buf, mime)

    digest = hashlib.sha256(buf).hexdigest()[:16]
    ext = _guess_ext(mime)
    fname = f"{digest}.{ext}"
    fpath = REF_DIR / fname
    if not fpath.exists():
        fpath.write_bytes(buf)

    _cleanup_ttl()
    _enforce_quota()

    base = _public_base(request).rstrip("/")
    return f"{base}/refs/{fname}"

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
    _check_referer(request.headers.get("referer"))

    if not json_data:
        raise HTTPException(status_code=400, detail="json_data (Form field) gerekli")

    try:
        payload = FormDataIn.model_validate_json(json_data)
    except ValidationError as ve:
        raise HTTPException(status_code=422, detail=ve.errors())

    ref_url = None
    if reference_image:
        ref_url = await _save_ref_and_get_url(reference_image, request)

    prompt = build_prompt(payload, reference_image_url=ref_url)
    return {"prompt": prompt}

@app.post("/generate-json", response_model=PromptOut)
async def generate_prompt_json(
    payload: FormDataIn,
    request: Request,
):
    _check_referer(request.headers.get("referer"))

    ref_url = None
    if payload.referenceImageBase64:
        # JSON yoluyla gelen base64'i de kısa URL'e çevir
        ref_url = await _save_base64_and_get_url(payload.referenceImageBase64, request)

    prompt = build_prompt(payload, reference_image_url=ref_url)
    return {"prompt": prompt}
