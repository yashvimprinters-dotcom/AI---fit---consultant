import os
import json
import base64
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from openai import (
    APIError,
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

app = FastAPI(title="AI Fit Consultant v5")
app.mount("/static", StaticFiles(directory="static"), name="static")

SYSTEM = """You are an AI clothing fit consultant.
Your job is to recommend the most appropriate SIZE FROM THE SELLER'S PROVIDED SIZE CHART.

Evidence rules:
- Treat explicit shopper measurements as the strongest body evidence.
- Height and weight are useful context but are NOT a substitute for chest, waist, inseam, shoulder, etc.
- The shopper photo is visual context only. Do NOT claim exact body measurements from a photo.
- Never infer or mention sensitive traits.
- Treat a seller chart as authoritative for that seller, but do not assume whether numbers are body measurements or garment measurements unless the user says so or the chart clearly labels it.
- If the chart is a screenshot, carefully read the visible size labels and measurements. If text and screenshot disagree, say so and lower confidence.
- Consider the user's preferred fit and clothing category.
- Do not invent missing measurements or sizes.
- Confidence must reflect evidence quality, not certainty of the language. If critical measurements are missing or chart meaning is unclear, keep confidence modest.
- Never guarantee fit. Recommend checking the seller's return/exchange policy when uncertainty is material.

Return only JSON matching the requested schema."""

SCHEMA = {
    "type": "object",
    "properties": {
        "recommended_size": {"type": "string"},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "fit_summary": {"type": "string"},
        "reasoning": {"type": "string"},
        "size_notes": {"type": "string"},
        "caveats": {"type": "string"},
        "next_measurement": {"type": "string"}
    },
    "required": [
        "recommended_size", "confidence", "fit_summary", "reasoning",
        "size_notes", "caveats", "next_measurement"
    ],
    "additionalProperties": False
}


def demo_result():
    return {
        "recommended_size": "M",
        "confidence": 78,
        "fit_summary": "M appears to be the closest match for the supplied regular-fit preference.",
        "reasoning": "Demo result only. A real recommendation compares shopper measurements with the seller's actual size chart.",
        "size_notes": "Use the seller's measurements and check whether they describe the garment or the intended body measurement.",
        "caveats": "A photo cannot guarantee garment fit, especially around shoulders, chest, waist and fabric stretch.",
        "next_measurement": "Chest circumference would usually be the most useful next measurement for a T-shirt."
    }


def image_to_data_url(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"


def validate_image(upload: UploadFile, raw: bytes, label: str):
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"error": f"{label} must be under 8 MB."}, status_code=400)
    mime = upload.content_type or "image/jpeg"
    if not mime.startswith("image/"):
        return JSONResponse({"error": f"Please upload an image file for {label.lower()}."}, status_code=400)
    return None


@app.get("/", response_class=HTMLResponse)
def home():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health():
    return {"status": "ok", "product": "AI Fit Consultant v5"}


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
    size_chart_image: Optional[UploadFile] = File(None),
    demo: bool = Form(False),
):
    if demo:
        return JSONResponse(demo_result())

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

    prompt = f"""CLOTHING CATEGORY: {category}
HEIGHT: {height_cm} cm
WEIGHT: {weight_kg if weight_kg is not None else 'not provided'} kg
DIRECT BODY MEASUREMENTS: {measurement_text}
PREFERRED FIT: {fit_preference}
SELLER CHART MEASUREMENT TYPE: {chart_measurement_type}

SELLER SIZE CHART TEXT:
{chart_text}

A seller size-chart image may also be attached. Read it if present.

Task:
1. Identify the available seller sizes and measurements from the supplied chart.
2. Compare them with the shopper's explicit measurements when available.
3. Use height/weight only as secondary context and use the photo only as visual context; do not turn the photo into exact measurements.
4. Account for the requested fit preference.
5. Recommend exactly one available seller size, or the closest available size if evidence is incomplete.
6. Explain what evidence drove the recommendation and what remains uncertain.
7. If the chart's numbers are ambiguous (for example garment vs body measurements), explicitly say so.
8. Calibrate confidence conservatively. Do not assign high confidence when key measurements are missing or chart interpretation is uncertain."""

    model = os.getenv("FIT_MODEL", "gpt-5.6-luna")

    content = [
        {"type": "input_text", "text": prompt},
        {"type": "input_image", "image_url": photo_data_url},
    ]
    if chart_data_url:
        content.append({"type": "input_image", "image_url": chart_data_url})

    try:
        client = OpenAI(api_key=key, timeout=60.0, max_retries=1)
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
        )
        result = json.loads(response.output_text)
        return JSONResponse(result)

    except AuthenticationError as e:
        print(f"OPENAI_AUTH_ERROR model={model}: {e}", flush=True)
        return JSONResponse({
            "error": "OpenAI authentication failed. Check OPENAI_API_KEY in Render.",
            "details": "The API key was rejected by OpenAI."
        }, status_code=502)
    except BadRequestError as e:
        print(f"OPENAI_BAD_REQUEST model={model}: {e}", flush=True)
        return JSONResponse({"error": "OpenAI rejected the request.", "details": str(e)}, status_code=502)
    except RateLimitError as e:
        print(f"OPENAI_RATE_LIMIT model={model}: {e}", flush=True)
        return JSONResponse({"error": "OpenAI rate limit or billing/quota issue.", "details": str(e)}, status_code=502)
    except APIConnectionError as e:
        print(f"OPENAI_CONNECTION_ERROR model={model}: {e}", flush=True)
        return JSONResponse({"error": "Could not connect to OpenAI.", "details": str(e)}, status_code=502)
    except APIError as e:
        print(f"OPENAI_API_ERROR model={model}: {e}", flush=True)
        return JSONResponse({"error": "OpenAI API error.", "details": str(e)}, status_code=502)
    except json.JSONDecodeError as e:
        print(f"OPENAI_JSON_ERROR model={model}: {e}", flush=True)
        return JSONResponse({"error": "The AI returned an unexpected response format.", "details": str(e)}, status_code=502)
    except Exception as e:
        print(f"UNEXPECTED_RECOMMEND_ERROR model={model}: {type(e).__name__}: {e}", flush=True)
        return JSONResponse({"error": "AI request failed.", "details": f"{type(e).__name__}: {e}"}, status_code=500)
