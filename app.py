import os
import json
import base64
import tempfile
from pathlib import Path
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

app = FastAPI(title="AI Fit Consultant v12")
app.mount("/static", StaticFiles(directory="static"), name="static")

SYSTEM = """You are an AI clothing fit and style consultant.
Your job is to recommend the most appropriate SIZE FROM THE SELLER'S PROVIDED SIZE CHART and provide practical color/style suggestions.

Fit evidence rules:
- Treat explicit shopper measurements as the strongest body evidence.
- Height and weight are useful context but are NOT a substitute for chest, waist, inseam, shoulder, etc.
- The shopper photo is visual context only. Do NOT claim exact body measurements from a photo.
- Never infer or mention race, ethnicity, religion, or other sensitive traits.
- Treat a seller chart as authoritative for that seller, but do not assume whether numbers are body measurements or garment measurements unless the user says so or the chart clearly labels it.
- If a seller chart is a screenshot, carefully read the visible size labels and measurements. If text and screenshot disagree, say so and lower confidence.
- Consider the user's preferred fit and clothing category.
- Do not invent missing measurements or sizes.
- Confidence must reflect evidence quality, not certainty of the language. If critical measurements are missing or chart meaning is unclear, keep confidence modest.
- Never guarantee fit. Recommend checking the seller's return/exchange policy when uncertainty is material.

Color and style rules:
- Give color suggestions as styling guidance, not as objective judgments about attractiveness.
- If the user provides a self-selected complexion undertone (warm, cool, neutral), use it to suggest harmonious colors. If it is unknown, give a flexible palette and explain that color preference and lighting matter.
- You may use visible color harmony cues in the shopper photo for clothing coordination, but do not classify the person by race or ethnicity.
- Suggest 3-5 wearable colors, 2-4 outfit color combinations, and 2-4 practical styling tips relevant to the selected clothing category and preferred fit.
- Avoid claiming that any color is universally best.

Return only JSON matching the requested schema."""

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
    return {"status": "ok", "product": "AI Fit Consultant v12"}


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
COMPLEXION UNDERTONE (USER-SELECTED): {complexion_undertone}
OCCASION: {occasion}

SELLER SIZE CHART TEXT:
{chart_text}

A seller size-chart image may also be attached. Read it if present.

Task:
1. Identify the available seller sizes and measurements from the supplied chart. Copy only measurements actually visible in the supplied text/image; never invent missing values. Put every available size into size_chart_rows, with measurements as a concise string such as "Chest 38 in • Shoulder 16 in • Length 27 in".
2. Compare them with the shopper's explicit measurements when available.
3. Use height/weight only as secondary context and use the photo only as visual context; do not turn the photo into exact measurements.
4. Account for the requested fit preference.
5. Recommend exactly one available seller size, or the closest available size if evidence is incomplete.
6. Explain what evidence drove the recommendation and what remains uncertain.
7. If the chart's numbers are ambiguous (for example garment vs body measurements), explicitly say so.
8. Calibrate confidence conservatively. Do not assign high confidence when key measurements are missing or chart interpretation is uncertain.
9. Provide 3-5 clothing colors that are likely to harmonize with the user's selected undertone and the photo's visible color context, without making claims about race or ethnicity.
10. Provide 2-4 simple outfit color combinations for the selected category and occasion.
11. Provide 2-4 styling tips based on category, preferred fit, and visible clothing/style context. Do not make insulting or appearance-shaming judgments.
12. If undertone is Not sure, keep the palette flexible and say that lighting and personal preference can change how colors appear."""

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
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return JSONResponse({"error": "Server API key is not configured. Configure OPENAI_API_KEY in Render."}, status_code=500)

    color = (custom_color.strip() or selected_color.strip() or "Navy")
    outfit = (custom_outfit.strip() or selected_outfit.strip() or "T-shirt + jeans")
    prompt = f"""Create exactly 3 complete clothing looks for a shopper.
CATEGORY: {category}
PREFERRED FIT: {fit_preference}
OCCASION: {occasion}
USER-SELECTED UNDERTONE: {complexion_undertone}
CURRENT MAIN COLOUR: {color}
CURRENT OUTFIT IDEA: {outfit}

Rules:
- Make three meaningfully different, wearable looks.
- Keep the current main colour/outfit idea as one of the three looks, while improving the rest of the styling where useful.
- Use ordinary clothing names that a customer can understand.
- Do not infer race or ethnicity.
- Styling guidance should be practical, not claims about attractiveness.
- Each look must include main color, outfit, bottom color, footwear and accessories.
- Keep combinations appropriate to the occasion and category.
- If the category is a garment such as a T-shirt, the main color applies to that main garment.
"""
    model = os.getenv("FIT_MODEL", "gpt-5.6-luna")
    try:
        client = OpenAI(api_key=key, timeout=60.0, max_retries=1)
        response = client.responses.create(
            model=model,
            instructions="You are a practical clothing stylist. Return only the requested JSON.",
            input=prompt,
            text={"format": {"type": "json_schema", "name": "look_builder", "schema": LOOK_SCHEMA, "strict": True}},
        )
        return JSONResponse(json.loads(response.output_text))
    except AuthenticationError:
        return JSONResponse({"error": "OpenAI authentication failed. Check OPENAI_API_KEY in Render."}, status_code=502)
    except RateLimitError as e:
        return JSONResponse({"error": "OpenAI rate limit or billing/quota issue.", "details": str(e)}, status_code=502)
    except BadRequestError as e:
        return JSONResponse({"error": "OpenAI rejected the look-building request.", "details": str(e)}, status_code=502)
    except APIConnectionError as e:
        return JSONResponse({"error": "Could not connect to OpenAI.", "details": str(e)}, status_code=502)
    except APIError as e:
        return JSONResponse({"error": "OpenAI API error.", "details": str(e)}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": "Could not build the looks.", "details": f"{type(e).__name__}: {e}"}, status_code=500)


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

        client = OpenAI(api_key=key, timeout=120.0, max_retries=1)
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
        return JSONResponse({"error": "OpenAI rejected the try-on image request.", "details": str(e)}, status_code=502)
    except RateLimitError as e:
        print(f"OPENAI_RATE_LIMIT image_model={model}: {e}", flush=True)
        return JSONResponse({"error": "OpenAI rate limit or billing/quota issue.", "details": str(e)}, status_code=502)
    except APIConnectionError as e:
        print(f"OPENAI_CONNECTION_ERROR image_model={model}: {e}", flush=True)
        return JSONResponse({"error": "Could not connect to OpenAI for the try-on preview.", "details": str(e)}, status_code=502)
    except APIError as e:
        print(f"OPENAI_API_ERROR image_model={model}: {e}", flush=True)
        return JSONResponse({"error": "The try-on image request failed.", "details": str(e)}, status_code=502)
    except Exception as e:
        print(f"TRY_ON_ERROR model={model}: {e}", flush=True)
        return JSONResponse({"error": "The visual try-on preview failed.", "details": str(e)}, status_code=500)
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
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
