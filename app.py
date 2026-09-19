import os
import json
import base64
import tempfile
import re
import time
import hashlib
import asyncio
from collections import defaultdict
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from openai import (
    APIError,
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

app = FastAPI(
    title="FITORA",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Production hardening: keep the public API small, reject oversized requests,
# add browser security headers, and apply per-instance request throttling.
RATE_BUCKETS = defaultdict(list)
RATE_LOCK = asyncio.Lock()
RATE_RULES = {
    "/api/recommend": (12, 60),
    "/api/build-look": (12, 60),
    "/api/build-looks": (20, 60),
    "/api/try-on": (4, 60),
    "/api/try-on-exact": (4, 60),
    "__default__": (90, 60),
}
MAX_REQUEST_BYTES = 45 * 1024 * 1024

async def _allow_request(request: Request):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True, 0
    path = request.url.path
    limit, window = RATE_RULES.get(path, RATE_RULES["__default__"])
    # Render normally supplies X-Forwarded-For from its proxy. If unavailable,
    # fall back to the socket address. This is a protective throttle, not auth.
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    key = f"{client_ip}:{path}"
    now = time.monotonic()
    async with RATE_LOCK:
        bucket = [t for t in RATE_BUCKETS[key] if now - t < window]
        if len(bucket) >= limit:
            RATE_BUCKETS[key] = bucket
            return False, max(1, int(window - (now - bucket[0])))
        bucket.append(now)
        RATE_BUCKETS[key] = bucket
        # Keep memory bounded.
        if len(RATE_BUCKETS) > 3000:
            for k in list(RATE_BUCKETS)[:500]:
                RATE_BUCKETS.pop(k, None)
    return True, 0

@app.middleware("http")
async def security_middleware(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return JSONResponse({"error": "Request is too large."}, status_code=413)
        except ValueError:
            return JSONResponse({"error": "Invalid request."}, status_code=400)
    allowed, retry_after = await _allow_request(request)
    if not allowed:
        return JSONResponse(
            {"error": "Too many requests. Please wait a moment and try again.", "code": "request_rate_limited"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    try:
        response = await call_next(request)
    except Exception:
        # Never expose stack traces or provider/internal details to browsers.
        return JSONResponse({"error": "FITORA could not complete that request."}, status_code=500)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.get("/manifest.webmanifest")
@app.get("/manifest.json")
async def pwa_manifest():
    return JSONResponse(content={
        "id": "/?source=pwa", "name": "FITORA – Your fit. Your style. Your look.", "short_name": "FITORA",
        "description": "AI fashion consultant for fit, size, outfits and visual try-on.",
        "start_url": "/?source=pwa", "scope": "/", "display": "standalone", "orientation": "portrait-primary",
        "background_color": "#10051f", "theme_color": "#10051f",
        "categories": ["lifestyle", "shopping"],
        "icons": [
            {"src": "/static/icons/fitora-icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/fitora-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/icons/fitora-icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": "/static/icons/fitora-icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }, headers={"Cache-Control":"no-store"})

@app.get("/sw.js")
async def pwa_service_worker():
    return Response(content=Path("static/sw.js").read_text(encoding="utf-8"), media_type="application/javascript", headers={"Cache-Control": "no-cache"})

app.mount("/static", StaticFiles(directory="static"), name="static")

SYSTEM = """You are FITORA, a practical clothing fit and style consultant.
Use the seller chart + explicit shopper measurements to recommend exactly one available size. Photo is visual context only and never a source of exact measurements. Do not infer sensitive traits. Do not guarantee fit. If chart meaning is unclear, say so and lower confidence. Use undertone only when user supplied it. Return only the requested JSON."""

SCHEMA = {
    "type": "object",
    "properties": {
        "recommended_size": {"type": "string"},
        "size_chart_rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "size": {"type": "string"},
                    "measurements": {"type": "string"}
                },
                "required": ["size", "measurements"],
                "additionalProperties": False
            },
            "minItems": 1,
            "maxItems": 30
        },
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "fit_summary": {"type": "string"},
        "reasoning": {"type": "string"},
        "size_notes": {"type": "string"},
        "caveats": {"type": "string"},
        "next_measurement": {"type": "string"},
        "color_palette": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 5},
        "color_combinations": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
        "style_tips": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4}
    },
    "required": [
        "recommended_size", "size_chart_rows", "confidence", "fit_summary", "reasoning",
        "size_notes", "caveats", "next_measurement", "color_palette",
        "color_combinations", "style_tips"
    ],
    "additionalProperties": False
}


LOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "looks": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "main_color": {"type": "string"},
                    "outfit": {"type": "string"},
                    "bottom_color": {"type": "string"},
                    "footwear": {"type": "string"},
                    "accessories": {"type": "string"},
                    "why": {"type": "string"}
                },
                "required": ["name","main_color","outfit","bottom_color","footwear","accessories","why"],
                "additionalProperties": False
            }
        }
    },
    "required": ["looks"],
    "additionalProperties": False
}

def demo_result():
    return {
        "recommended_size": "M",
        "size_chart_rows": [
            {"size": "S", "measurements": "Enter seller chart"},
            {"size": "M", "measurements": "Enter seller chart"},
            {"size": "L", "measurements": "Enter seller chart"}
        ],
        "confidence": 78,
        "fit_summary": "M appears to be the closest match for the supplied regular-fit preference.",
        "reasoning": "Demo result only. A real recommendation compares shopper measurements with the seller's actual size chart.",
        "size_notes": "Use the seller's measurements and check whether they describe the garment or the intended body measurement.",
        "caveats": "A photo cannot guarantee garment fit, especially around shoulders, chest, waist and fabric stretch.",
        "next_measurement": "Chest circumference would usually be the most useful next measurement for a T-shirt.",
        "color_palette": ["Navy", "White", "Olive", "Charcoal"],
        "color_combinations": ["Navy + white", "Olive + cream", "Charcoal + white"],
        "style_tips": ["Use a clean regular-fit silhouette.", "Keep the main garment neutral and add one accent color."]
    }


def image_to_data_url(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"


def validate_image(upload: UploadFile, raw: bytes, label: str):
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"error": f"{label} must be under 8 MB."}, status_code=400)
    mime = (upload.content_type or "").lower()
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if mime not in allowed:
        return JSONResponse({"error": f"Please upload a JPG, PNG, or WebP image for {label.lower()}."}, status_code=400)
    # Check the actual file signature instead of trusting Content-Type alone.
    signatures = {
        "image/jpeg": raw[:3] == b"\xff\xd8\xff",
        "image/png": raw[:8] == b"\x89PNG\r\n\x1a\n",
        "image/webp": len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP",
    }
    if not signatures.get(mime, False):
        return JSONResponse({"error": f"The {label.lower()} file is not a valid image."}, status_code=400)
    return None

def _bounded(value: str, limit: int, label: str = "value"):
    value = (value or "").strip()
    if len(value) > limit:
        raise ValueError(f"{label} is too long.")
    return value


@app.get("/", response_class=HTMLResponse)
def home():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health():
    return {"status": "ok", "product": "FITORA", "security": "hardened", "ai_model": _model_name(), "ai_configured": bool(os.getenv("OPENAI_API_KEY")), "photo_in_recommendation": os.getenv("FIT_INCLUDE_PHOTO_IN_RECOMMEND", "false").lower() == "true"}


@app.get("/api/public-config")
def public_config():
    # Only non-secret browser configuration is exposed. Never expose OPENAI_API_KEY.
    return {
        "adsense_client_id": os.getenv("ADSENSE_CLIENT_ID", "").strip(),
        "referral_rewards_enabled": os.getenv("FITORA_REFERRAL_REWARDS_ENABLED", "false").lower() == "true",
    }



# v26 reliability layer: local fallbacks + safe, customer-friendly AI errors.

def _model_name():
    return os.getenv("FIT_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"

# Small per-instance cache: avoids paying tokens for duplicate taps/reloads.
_AI_CACHE = OrderedDict()
_AI_CACHE_MAX = 128

def _cache_key(prefix, payload):
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return prefix + ":" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _cache_get(key):
    value = _AI_CACHE.get(key)
    if value is not None:
        _AI_CACHE.move_to_end(key)
    return value

def _cache_put(key, value):
    _AI_CACHE[key] = value
    _AI_CACHE.move_to_end(key)
    while len(_AI_CACHE) > _AI_CACHE_MAX:
        _AI_CACHE.popitem(last=False)
    return value


def _safe_ai_client(key, timeout=60.0):
    # Do not add application-level retries on top of SDK/provider retry behavior.
    # Repeated failed requests can themselves contribute to rate-limit pressure.
    return OpenAI(api_key=key, timeout=timeout, max_retries=0)


def _error_code(exc):
    return str(getattr(exc, "code", "") or "").lower()


def _retry_after(exc):
    try:
        headers = getattr(getattr(exc, "response", None), "headers", None)
        value = headers.get("retry-after") if headers else None
        if value is not None:
            return max(0, int(float(value)))
    except Exception:
        pass
    return None


def _ai_error(exc, feature):
    code = _error_code(exc)
    retry_after = _retry_after(exc)
    if isinstance(exc, RateLimitError):
        if "credit_balance" in code or "quota" in code or "usage_limit" in code or "spend_limit" in code:
            message = "AI styling is temporarily unavailable because the AI service has reached its account limit."
            kind = "ai_quota"
        else:
            message = "FITORA is busy right now. You can continue with the built-in fashion suggestions, or try the AI feature again later."
            kind = "ai_rate_limited"
        payload = {"error": message, "code": kind, "feature": feature}
        if retry_after is not None:
            payload["retry_after_seconds"] = retry_after
        return JSONResponse(payload, status_code=429)
    if isinstance(exc, AuthenticationError):
        return JSONResponse({"error": "FITORA's AI connection needs attention. Please try again later.", "code": "ai_auth"}, status_code=502)
    if isinstance(exc, APIConnectionError):
        return JSONResponse({"error": "FITORA could not reach the AI service. Please check your connection and try again.", "code": "ai_connection"}, status_code=503)
    if isinstance(exc, BadRequestError):
        return JSONResponse({"error": "FITORA could not process that request. Please check the uploaded images and details.", "code": "ai_bad_request"}, status_code=400)
    if isinstance(exc, APIError):
        return JSONResponse({"error": "The AI service could not complete this request. Please try again.", "code": "ai_error"}, status_code=502)
    return JSONResponse({"error": "FITORA could not complete this request. Please try again.", "code": "ai_error"}, status_code=500)


def _parse_size_chart(text):
    """Parse common text charts for a useful offline fallback. Never invent rows."""
    rows = []
    if not text or not text.strip():
        return rows
    size_re = re.compile(r"^\s*([A-Za-z0-9]{1,6}(?:[-/][A-Za-z0-9]{1,6})?)\s*[-:|—–]\s*(.+?)\s*$")
    for line in text.replace("•", "|").splitlines():
        m = size_re.match(line)
        if not m:
            continue
        size, measurements = m.group(1).strip(), m.group(2).strip()
        if not re.search(r"\d", measurements):
            continue
        rows.append({"size": size, "measurements": measurements})
    return rows[:30]


def _numbers_by_measurement(text):
    out = {}
    patterns = {
        "chest": r"(?:chest|bust)\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(cm|in|inch|inches)?",
        "waist": r"waist\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(cm|in|inch|inches)?",
        "shoulder": r"shoulder\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(cm|in|inch|inches)?",
        "inseam": r"inseam\s*[:=]?\s*(\d+(?:\.\d+)?)\s*(cm|in|inch|inches)?",
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, re.I)
        if m:
            value = float(m.group(1)); unit = (m.group(2) or "cm").lower()
            if unit.startswith("in"):
                value *= 2.54
            out[key] = value
    return out


def _local_recommendation(category, fit_preference, occasion, measurements, chart_text, undertone):
    rows = _parse_size_chart(chart_text)
    if not rows:
        return None
    target = {"chest": measurements.get("chest_cm"), "waist": measurements.get("waist_cm"), "shoulder": measurements.get("shoulder_cm"), "inseam": measurements.get("inseam_cm")}
    target = {k: float(v) for k, v in target.items() if v is not None}
    scored=[]
    for row in rows:
        vals=_numbers_by_measurement(row["measurements"])
        diffs=[]
        for k,v in target.items():
            if k in vals:
                diffs.append(abs(vals[k]-v)/max(v,1.0))
        score=sum(diffs)/len(diffs) if diffs else 0.18
        scored.append((score,row,vals))
    scored.sort(key=lambda x:x[0])
    chosen=scored[0][1]
    matched=sum(1 for k in target if k in scored[0][2])
    confidence=55 if matched else 38
    if matched>=2: confidence=68
    if matched>=3: confidence=76
    if fit_preference.lower() in {"slim","oversized","relaxed"}: confidence=max(45, confidence-5)
    palette={
      "warm":["Cream","Camel","Olive","Rust","Warm brown"],
      "cool":["Navy","Charcoal","White","Burgundy","Cool blue"],
      "neutral":["Navy","White","Olive","Charcoal","Beige"],
      "not sure":["Navy","White","Olive","Charcoal","Beige"],
    }.get((undertone or "Not sure").lower(), ["Navy","White","Olive","Charcoal","Beige"])
    return {
      "recommended_size": chosen["size"], "size_chart_rows": rows, "confidence": confidence,
      "fit_summary": f"{chosen['size']} is the closest match from the seller chart using the measurements you provided. This is an offline fallback because live AI is temporarily unavailable.",
      "reasoning": "The fallback compared the available chart measurements with your directly entered measurements where the chart text was clear. It did not use your photo as a source of exact body measurements.",
      "size_notes": "Check whether the seller's numbers are body measurements or garment measurements. The fallback cannot reliably infer that distinction from an unclear chart.",
      "caveats": "This is a fallback estimate, not a guarantee of fit. Fabric stretch, cut and seller measurement method can change the result.",
      "next_measurement": "Add the measurement that matches the seller chart but is still missing, such as chest, waist, shoulder or inseam.",
      "color_palette": palette, "color_combinations": [f"{palette[0]} + {palette[1]}", f"{palette[2]} + {palette[1]}", f"{palette[0]} + {palette[4]}"],
      "style_tips": [f"Use a {fit_preference.lower()} silhouette as selected.", f"For {occasion.lower()}, keep the main garment simple and add one coordinated accent.", "Check the seller return/exchange policy before ordering when fit is uncertain."],
      "source":"local_fallback", "ai_unavailable":True
    }


def _local_looks(category, fit, occasion, color, outfit):
    c=color or "Navy"; o=outfit or "T-shirt + jeans"; occ=(occasion or "Everyday casual").lower()
    if "formal" in occ or "work" in occ:
        sets=[(c,"Oxford shirt + tailored trousers","Black","Loafers","Watch + belt"),(c,"Polo + chinos","Beige","Loafers","Watch"),("White","Shirt + blazer + trousers","Charcoal","Formal shoes","Watch + belt")]
    elif "wedding" in occ or "festive" in occ:
        sets=[(c,"Kurta + trousers","Cream","Traditional footwear","Watch"),("Ivory","Kurta set + dupatta","Beige","Traditional footwear","Minimal jewellery"),("Navy","Nehru jacket + kurta + trousers","Cream","Traditional footwear","Watch")]
    elif "party" in occ or "evening" in occ or "date" in occ:
        sets=[(c,o,"Black","Loafers","Watch"),("Black","Blazer + T-shirt + jeans","Dark denim","Clean sneakers","Watch"),("Burgundy","Polo + dark trousers","Black","Loafers","Watch + belt")]
    else:
        sets=[(c,o,"Blue","White sneakers","Watch"),("Olive","Overshirt + T-shirt + trousers","Beige","Neutral sneakers","Watch"),("White","Polo + chinos","Khaki","Casual loafers","Watch + belt")]
    return {"looks":[{"name":f"Look {i+1}","main_color":a,"outfit":b,"bottom_color":d,"footwear":e,"accessories":f,"why":f"A practical {occ} combination using your selected {fit.lower()} fit preference."} for i,(a,b,d,e,f) in enumerate(sets)] ,"source":"local_fallback","ai_unavailable":True}

@app.post("/api/recommend")
async def recommend(
    photo: UploadFile = File(...),
    height_cm: float = Form(...),
    weight_kg: Optional[float] = Form(None),
    chest_cm: Optional[float] = Form(None),
    waist_cm: Optional[float] = Form(None),
    inseam_cm: Optional[float] = Form(None),
    shoulder_cm: Optional[float] = Form(None),
    fit_preference: str = Form(...),
    category: str = Form(...),
    size_chart: str = Form(""),
    chart_measurement_type: str = Form("Unknown"),
    complexion_undertone: str = Form("Not sure"),
    occasion: str = Form("Everyday casual"),
    size_chart_image: Optional[UploadFile] = File(None),
    demo: bool = Form(False),
):
    if demo:
        return JSONResponse(demo_result())

    try:
        category = _bounded(category, 80, "Category")
        fit_preference = _bounded(fit_preference, 40, "Fit preference")
        occasion = _bounded(occasion, 80, "Occasion")
        complexion_undertone = _bounded(complexion_undertone, 40, "Undertone")
        chart_measurement_type = _bounded(chart_measurement_type, 40, "Chart type")
        size_chart = _bounded(size_chart, 6000, "Size chart")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if not size_chart.strip() and size_chart_image is None:
        return JSONResponse({
            "error": "Provide the seller's size chart as text or upload a screenshot/photo of the chart."
        }, status_code=400)

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return JSONResponse({
            "error": "Server API key is not configured. Configure OPENAI_API_KEY in Render."
        }, status_code=500)

    raw_photo = await photo.read()
    error = validate_image(photo, raw_photo, "Photo")
    if error:
        return error
    photo_mime = photo.content_type or "image/jpeg"
    photo_data_url = image_to_data_url(raw_photo, photo_mime)

    chart_data_url = None
    if size_chart_image is not None:
        raw_chart = await size_chart_image.read()
        error = validate_image(size_chart_image, raw_chart, "Size-chart image")
        if error:
            return error
        chart_mime = size_chart_image.content_type or "image/jpeg"
        chart_data_url = image_to_data_url(raw_chart, chart_mime)

    measurements = []
    for label, value in [
        ("Chest", chest_cm),
        ("Waist", waist_cm),
        ("Inseam", inseam_cm),
        ("Shoulder", shoulder_cm),
    ]:
        if value is not None:
            measurements.append(f"{label}: {value} cm")
    measurement_text = ", ".join(measurements) if measurements else "No direct body measurements provided"

    chart_text = size_chart.strip() if size_chart.strip() else "No size-chart text entered; use the uploaded chart image."

    prompt = f"""CATEGORY:{category}
FIT:{fit_preference}
OCCASION:{occasion}
UNDERTONE:{complexion_undertone}
MEASUREMENTS:{'; '.join(measurements) if measurements else 'none'}
CHART_TYPE:{chart_measurement_type}
SELLER_CHART:{size_chart.strip() or '[image attached]'}

Return one available size. Include concise evidence, caveat, next missing measurement, 3-5 colors, 2-4 color combinations and 2-4 practical styling tips. Keep every text field short."""

    model = _model_name()

    cache_payload = {"category": category, "fit": fit_preference, "occasion": occasion, "undertone": complexion_undertone, "measurements": measurements, "chart_type": chart_measurement_type, "chart": size_chart.strip(), "chart_image": hashlib.sha256((raw_chart if size_chart_image is not None else b"")).hexdigest()}
    cache_key = _cache_key("recommend", cache_payload)
    cached = _cache_get(cache_key)
    if cached is not None:
        return JSONResponse(cached)

    content = [{"type": "input_text", "text": prompt}]
    # Photo analysis is opt-in because image input is a major token cost.
    if os.getenv("FIT_INCLUDE_PHOTO_IN_RECOMMEND", "false").lower() == "true":
        content.append({"type": "input_image", "image_url": photo_data_url})
    if chart_data_url:
        content.append({"type": "input_image", "image_url": chart_data_url})

    try:
        client = _safe_ai_client(key, timeout=60.0)
        response = client.responses.create(
            model=model,
            instructions=SYSTEM,
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "fit_recommendation",
                    "schema": SCHEMA,
                    "strict": True,
                }
            },
            max_output_tokens=800,
        )
        result = json.loads(response.output_text)
        return JSONResponse(_cache_put(cache_key, result))

    except AuthenticationError as e:
        print(f"OPENAI_AUTH_ERROR model={model}: {e}", flush=True)
        return JSONResponse({
            "error": "OpenAI authentication failed. Check OPENAI_API_KEY in Render.",
            "details": "Provider authentication failed."
        }, status_code=502)
    except BadRequestError as e:
        print(f"OPENAI_BAD_REQUEST model={model}: {e}", flush=True)
        return JSONResponse({"error": "OpenAI rejected the request.", "details": "The request was rejected by an external service."}, status_code=502)
    except RateLimitError as e:
        print(f"OPENAI_RATE_LIMIT model={model}: {e}", flush=True)
        fallback = _local_recommendation(category, fit_preference, occasion, {"chest_cm": chest_cm, "waist_cm": waist_cm, "shoulder_cm": shoulder_cm, "inseam_cm": inseam_cm}, size_chart, complexion_undertone)
        if fallback:
            return JSONResponse(fallback)
        return _ai_error(e, "size recommendation")
    except APIConnectionError as e:
        print(f"OPENAI_CONNECTION_ERROR model={model}: {e}", flush=True)
        return JSONResponse({"error": "Could not connect to OpenAI.", "details": "The request was rejected by an external service."}, status_code=502)
    except APIError as e:
        print(f"OPENAI_API_ERROR model={model}: {e}", flush=True)
        return JSONResponse({"error": "OpenAI API error.", "details": "The request was rejected by an external service."}, status_code=502)
    except json.JSONDecodeError as e:
        print(f"OPENAI_JSON_ERROR model={model}: {e}", flush=True)
        return JSONResponse({"error": "The AI returned an unexpected response format.", "details": "The request was rejected by an external service."}, status_code=502)
    except Exception as e:
        print(f"UNEXPECTED_RECOMMEND_ERROR model={model}: {type(e).__name__}: {e}", flush=True)
        return JSONResponse({"error": "AI request failed.", "details": "An internal error occurred."}, status_code=500)


@app.post("/api/build-look")
async def build_look(
    category: str = Form("Men's T-shirt"),
    fit_preference: str = Form("Regular"),
    occasion: str = Form("Everyday casual"),
    complexion_undertone: str = Form("Not sure"),
    selected_color: str = Form("Navy"),
    selected_outfit: str = Form("T-shirt + jeans"),
    custom_color: str = Form(""),
    custom_outfit: str = Form(""),
):
    try:
        category = _bounded(category, 80, "Category")
        fit_preference = _bounded(fit_preference, 40, "Fit preference")
        occasion = _bounded(occasion, 80, "Occasion")
        complexion_undertone = _bounded(complexion_undertone, 40, "Undertone")
        selected_color = _bounded(selected_color, 60, "Color")
        selected_outfit = _bounded(selected_outfit, 120, "Outfit")
        custom_color = _bounded(custom_color, 60, "Custom color")
        custom_outfit = _bounded(custom_outfit, 120, "Custom outfit")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return JSONResponse({"error": "Server API key is not configured. Configure OPENAI_API_KEY in Render."}, status_code=500)

    color = (custom_color.strip() or selected_color.strip() or "Navy")
    outfit = (custom_outfit.strip() or selected_outfit.strip() or "T-shirt + jeans")
    prompt = f"""Create 3 wearable looks.
CATEGORY:{category}; FIT:{fit_preference}; OCCASION:{occasion}; UNDERTONE:{complexion_undertone}; COLOR:{color}; BASE:{outfit}
Keep one look close to COLOR+BASE. Each look needs name, main_color, outfit, bottom_color, footwear, accessories, why. Keep each field concise."""
    model = _model_name()
    cache_key = _cache_key("build-look", {"category":category,"fit":fit_preference,"occasion":occasion,"undertone":complexion_undertone,"color":color,"outfit":outfit})
    cached = _cache_get(cache_key)
    if cached is not None:
        return JSONResponse(cached)
    try:
        client = _safe_ai_client(key, timeout=60.0)
        response = client.responses.create(
            model=model,
            instructions="You are a practical clothing stylist. Return only the requested JSON.",
            input=prompt,
            text={"format": {"type": "json_schema", "name": "look_builder", "schema": LOOK_SCHEMA, "strict": True}},
            max_output_tokens=500,
        )
        return JSONResponse(_cache_put(cache_key, json.loads(response.output_text)))
    except AuthenticationError:
        return JSONResponse({"error": "OpenAI authentication failed. Check OPENAI_API_KEY in Render."}, status_code=502)
    except RateLimitError as e:
        print(f"OPENAI_RATE_LIMIT build_look model={model}: {e}", flush=True)
        return JSONResponse(_local_looks(category, fit_preference, occasion, color, outfit))
    except BadRequestError as e:
        return JSONResponse({"error": "OpenAI rejected the look-building request.", "details": "The request was rejected by an external service."}, status_code=502)
    except APIConnectionError as e:
        return JSONResponse({"error": "Could not connect to OpenAI.", "details": "The request was rejected by an external service."}, status_code=502)
    except APIError as e:
        return JSONResponse({"error": "OpenAI API error.", "details": "The request was rejected by an external service."}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": "Could not build the looks.", "details": "An internal error occurred."}, status_code=500)


@app.post("/api/try-on")
async def try_on(
    photo: UploadFile = File(...),
    selected_color: str = Form("Navy"),
    selected_outfit: str = Form("T-shirt + jeans"),
    category: str = Form("Men's T-shirt"),
    fit_preference: str = Form("Regular"),
    bottom_color: str = Form("Black"),
    footwear: str = Form("No preference"),
    accessories: str = Form(""),
):
    """Create a visual styling preview by editing the shopper's uploaded photo.
    The image model is instructed to preserve the person, pose, face and background
    while changing clothing to the requested color/outfit.
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return JSONResponse({
            "error": "Server API key is not configured. Configure OPENAI_API_KEY in Render."
        }, status_code=500)

    raw_photo = await photo.read()
    error = validate_image(photo, raw_photo, "Photo")
    if error:
        return error

    color = selected_color.strip() or "Navy"
    outfit = selected_outfit.strip() or "T-shirt + jeans"
    category_name = category.strip() or "clothing"
    fit = fit_preference.strip() or "Regular"
    bottom = bottom_color.strip() or "Black"
    shoes = footwear.strip() or "No preference"
    accessory_text = accessories.strip() or "No specific accessories"

    prompt = f"""
Edit this shopper photo into a realistic clothing try-on preview.

CHANGE:
- Outfit: {outfit}
- Main garment/category: {category_name}
- Main garment color: {color}
- Preferred fit: {fit}
- Bottom colour: {bottom}
- Footwear: {shoes}
- Accessories: {accessory_text}

PRESERVE:
- The same person and facial identity
- Face, hair, skin appearance, body proportions and pose
- Camera angle and framing as much as possible
- Background, lighting and environment as much as possible
- Natural fabric folds, seams, shadows and realistic garment fit

IMPORTANT:
- Change clothing only; do not beautify, reshape, slim, enlarge or otherwise alter the person's body.
- Do not change the person's face or identity.
- Make the requested outfit clearly visible and wearable.
- If the original clothing covers an area, realistically replace that clothing rather than painting color over skin.
- This is a visual styling preview, not an exact measurement or fit guarantee.
Return one photorealistic edited image.
"""

    model = os.getenv("FIT_IMAGE_MODEL", "gpt-image-2")
    suffix = Path(photo.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(raw_photo)
            temp_path = tmp.name

        client = _safe_ai_client(key, timeout=120.0)
        async with _IMAGE_SEMAPHORE:
            response = client.images.edit(
                model=model,
                image=Path(temp_path),
                prompt=prompt,
                size="1024x1536",
                quality=os.getenv("FIT_IMAGE_QUALITY", "medium"),
                output_format="jpeg",
            )
        item = response.data[0]
        b64 = getattr(item, "b64_json", None)
        if not b64:
            return JSONResponse({
                "error": "The image service did not return an image."
            }, status_code=502)
        return JSONResponse({
            "image_data_url": "data:image/jpeg;base64," + b64,
            "selected_color": color,
            "selected_outfit": outfit,
            "bottom_color": bottom,
            "footwear": shoes,
            "accessories": accessory_text,
            "note": "AI visual preview only. The image may not represent exact garment fit or measurements."
        })
    except AuthenticationError as e:
        print(f"OPENAI_AUTH_ERROR image_model={model}: {e}", flush=True)
        return JSONResponse({"error": "OpenAI authentication failed. Check OPENAI_API_KEY in Render."}, status_code=502)
    except BadRequestError as e:
        print(f"OPENAI_BAD_REQUEST image_model={model}: {e}", flush=True)
        return _ai_error(e, "visual try-on")
    except RateLimitError as e:
        print(f"OPENAI_RATE_LIMIT image_model={model}: {e}", flush=True)
        return _ai_error(e, "visual try-on")
    except APIConnectionError as e:
        print(f"OPENAI_CONNECTION_ERROR image_model={model}: {e}", flush=True)
        return _ai_error(e, "visual try-on")
    except APIError as e:
        print(f"OPENAI_API_ERROR image_model={model}: {e}", flush=True)
        return _ai_error(e, "visual try-on")
    except Exception as e:
        print(f"TRY_ON_ERROR model={model}: {e}", flush=True)
        return JSONResponse({"error": "The visual try-on preview failed.", "details": "The request was rejected by an external service."}, status_code=500)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass



# V17 exact-product visual try-on
_IMAGE_SEMAPHORE = asyncio.Semaphore(2)
@app.post("/api/try-on-exact")
async def try_on_exact(
    photo: UploadFile = File(...),
    top_image: Optional[UploadFile] = File(None),
    bottom_image: Optional[UploadFile] = File(None),
    outerwear_image: Optional[UploadFile] = File(None),
    footwear_image: Optional[UploadFile] = File(None),
    accessory_image: Optional[UploadFile] = File(None),
    top_name: str = Form("Classic T-Shirt"),
    bottom_name: str = Form("Straight Jeans"),
    outerwear_name: str = Form("None"),
    footwear_name: str = Form("White Sneakers"),
    accessory_name: str = Form("Classic Watch"),
    changed_item: str = Form("all"),
):
    """Create a try-on using the shopper photo plus exact product reference images.

    The shopper photo is always the first image. Product references are optional; when
    supplied they are passed as additional references to the image-edit model.
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return JSONResponse({"error": "Server API key is not configured. Configure OPENAI_API_KEY in Render."}, status_code=500)

    uploads = [
        ("shopper", photo),
        ("top", top_image),
        ("bottom", bottom_image),
        ("outerwear", outerwear_image),
        ("footwear", footwear_image),
        ("accessory", accessory_image),
    ]
    raw = {}
    for label, upload in uploads:
        if upload is None:
            continue
        data = await upload.read()
        error = validate_image(upload, data, label.title())
        if error:
            return error
        raw[label] = data

    names = {
        "top": top_name.strip() or "Selected top",
        "bottom": bottom_name.strip() or "Selected bottom",
        "outerwear": outerwear_name.strip() or "None",
        "footwear": footwear_name.strip() or "Selected footwear",
        "accessory": accessory_name.strip() or "Selected accessory",
    }
    changed = changed_item.strip() or "all"

    prompt = f"""
Create a photorealistic full-body clothing try-on of the person in reference image 1.

REFERENCE IMAGE ROLES:
- Image 1 = the customer's original photo. Preserve this person, face, identity, body proportions, pose, camera framing and background as closely as possible.
- Any later images are exact product references. Match their visible garment/product design, colour, material, pattern, silhouette and important details as closely as possible.

SELECTED COMPLETE LOOK:
- Top: {names['top']}
- Bottom: {names['bottom']}
- Outerwear: {names['outerwear']}
- Footwear: {names['footwear']}
- Accessory: {names['accessory']}

THE ITEM THE CUSTOMER MAY HAVE JUST CHANGED: {changed}

RULES:
- Put the referenced products on the same person in a natural, realistic way.
- If a product reference is provided for an item, prioritize that reference over generic fashion knowledge.
- Do not invent a different brand, logo, pattern or major design when the reference clearly shows one.
- Change clothing/accessories only. Do not beautify, reshape, slim, enlarge or otherwise alter the person's body.
- Do not change the person's face or identity.
- Preserve realistic fabric folds, seams, shadows, scale and lighting.
- Keep the original environment unless a clothing change makes a tiny lighting adjustment necessary.
- This is a visual preview, not an exact fit or measurement guarantee.
Return one photorealistic edited image.
""".strip()

    model = os.getenv("FIT_IMAGE_MODEL", "gpt-image-2")
    suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    temp_paths = []
    try:
        for label, data in raw.items():
            original = next((u for l, u in uploads if l == label), None)
            suffix = Path(getattr(original, "filename", "") or "").suffix.lower() if original else ".jpg"
            if suffix not in suffixes:
                suffix = ".jpg"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(data)
                temp_paths.append((label, tmp.name))

        # Keep the shopper photo first. Additional images are exact product references.
        ordered_labels = ["shopper", "top", "bottom", "outerwear", "footwear", "accessory"]
        from contextlib import ExitStack
        with ExitStack() as stack:
            image_files = []
            for label in ordered_labels:
                match = next((path for l, path in temp_paths if l == label), None)
                if match:
                    image_files.append(stack.enter_context(open(match, "rb")))

            client = _safe_ai_client(key, timeout=180.0)
            kwargs = {
                "model": model,
                "image": image_files,
                "prompt": prompt,
                "size": os.getenv("FIT_IMAGE_SIZE", "1024x1536"),
                "quality": os.getenv("FIT_IMAGE_QUALITY", "medium"),
                "output_format": "jpeg",
            }
            # gpt-image-2 and later GPT image models support high/low input fidelity.
            fidelity = os.getenv("FIT_IMAGE_INPUT_FIDELITY", "high").strip().lower()
            if fidelity in {"high", "low"}:
                kwargs["input_fidelity"] = fidelity
            async with _IMAGE_SEMAPHORE:
                response = client.images.edit(**kwargs)
            item = response.data[0]
            b64 = getattr(item, "b64_json", None)
            if not b64:
                return JSONResponse({"error": "The image service did not return an image."}, status_code=502)
            return JSONResponse({
                "image_data_url": "data:image/jpeg;base64," + b64,
                "top": names["top"],
                "bottom": names["bottom"],
                "outerwear": names["outerwear"],
                "footwear": names["footwear"],
                "accessory": names["accessory"],
                "changed_item": changed,
                "reference_count": max(0, len(image_files) - 1),
                "note": "Exact-product visual preview using the uploaded product references. It is still an approximation and not an exact fit guarantee."
            })
    except AuthenticationError as e:
        print(f"OPENAI_AUTH_ERROR exact_try_on model={model}: {e}", flush=True)
        return JSONResponse({"error": "OpenAI authentication failed. Check OPENAI_API_KEY in Render."}, status_code=502)
    except BadRequestError as e:
        print(f"OPENAI_BAD_REQUEST exact_try_on model={model}: {e}", flush=True)
        return _ai_error(e, "exact-product try-on")
    except RateLimitError as e:
        print(f"OPENAI_RATE_LIMIT exact_try_on model={model}: {e}", flush=True)
        return _ai_error(e, "exact-product try-on")
    except APIConnectionError as e:
        print(f"OPENAI_CONNECTION_ERROR exact_try_on model={model}: {e}", flush=True)
        return _ai_error(e, "exact-product try-on")
    except APIError as e:
        print(f"OPENAI_API_ERROR exact_try_on model={model}: {e}", flush=True)
        return _ai_error(e, "exact-product try-on")
    except Exception as e:
        print(f"EXACT_TRY_ON_ERROR model={model}: {e}", flush=True)
        return JSONResponse({"error": "The exact-product visual try-on failed.", "details": "An internal error occurred."}, status_code=500)
    finally:
        for _, path in temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass

# v13 fashion knowledge endpoint
from pathlib import Path as _V13Path
from fastapi.responses import FileResponse as _V13FileResponse
@app.get("/fashion-knowledge.json")
def v13_fashion_knowledge():
    return _V13FileResponse(str(_V13Path(__file__).parent / "fashion_knowledge.json"), media_type="application/json")


# ---------------- V14 AI PERSONAL STYLIST ----------------
from stylist_engine import build_three_looks, visual_try_on_prompt

@app.post("/api/build-looks")
async def v14_build_looks(payload: dict):
    """Create three complete, coordinated looks from customer choices."""
    return {"looks": build_three_looks(payload or {})}

@app.post("/api/visual-tryon-prompt")
async def v14_visual_tryon_prompt(payload: dict):
    look = payload.get("look") or {}
    return {"prompt": visual_try_on_prompt(look, payload.get("customer_notes",""))}

# V15 visual fashion catalog endpoint
from pathlib import Path as _V15Path
from fastapi.responses import FileResponse as _V15FileResponse
@app.get("/visual-catalog.json")
def v15_visual_catalog():
    return _V15FileResponse(str(_V15Path(__file__).parent / "visual_catalog.json"), media_type="application/json")

# V16 product catalog endpoint
from pathlib import Path as _V16Path
from fastapi.responses import FileResponse as _V16FileResponse
@app.get("/product-catalog.json")
def v16_product_catalog():
    return _V16FileResponse(str(_V16Path(__file__).parent / "product_catalog.json"), media_type="application/json")
