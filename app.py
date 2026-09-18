import os, json, base64
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

app = FastAPI(title="AI Fit Consultant v3")
app.mount("/static", StaticFiles(directory="static"), name="static")

SYSTEM = """You are an AI clothing fit consultant.
Recommend the most appropriate SIZE FROM THE SELLER'S PROVIDED SIZE CHART.
Use explicit height, optional weight, fit preference, category and garment measurements.
The image is visual context only. Do not claim exact body measurements from a photo.
Do not infer or mention sensitive traits.
Never guarantee fit.
If evidence is weak or the chart lacks important measurements, lower confidence and clearly say so.
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
        "recommended_size","confidence","fit_summary","reasoning",
        "size_notes","caveats","next_measurement"
    ],
    "additionalProperties": False
}

def demo_result():
    return {
        "recommended_size": "M",
        "confidence": 78,
        "fit_summary": "M appears to be the closest match for the supplied regular-fit preference.",
        "reasoning": "Demo result only. A real recommendation would compare the shopper information with the seller's measurements.",
        "size_notes": "Check the seller's chest and length measurements before ordering.",
        "caveats": "A photo cannot guarantee garment fit, especially for shoulders, chest, waist and fabric stretch.",
        "next_measurement": "Chest circumference would improve confidence."
    }

@app.get("/", response_class=HTMLResponse)
def home():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/health")
def health():
    return {"status": "ok", "product": "AI Fit Consultant v3"}

@app.post("/api/recommend")
async def recommend(
    photo: UploadFile = File(...),
    height_cm: float = Form(...),
    weight_kg: float = Form(None),
    fit_preference: str = Form(...),
    category: str = Form(...),
    size_chart: str = Form(...),
    demo: bool = Form(False)
):
    if demo:
        return JSONResponse(demo_result())

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return JSONResponse({"error": "Server API key is not configured. Use Demo Mode or configure OPENAI_API_KEY."}, status_code=500)

    raw = await photo.read()
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"error": "Photo must be under 8 MB."}, status_code=400)

    mime = photo.content_type or "image/jpeg"
    if not mime.startswith("image/"):
        return JSONResponse({"error": "Please upload an image file."}, status_code=400)

    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('utf-8')}"

    prompt = f"""Clothing category: {category}
Height: {height_cm} cm
Weight: {weight_kg if weight_kg is not None else "not provided"} kg
Preferred fit: {fit_preference}

SELLER SIZE CHART:
{size_chart}

Recommend one available seller size. Explain uncertainty. If a critical garment measurement is missing, mention it."""

    try:
        client = OpenAI(api_key=key)
        response = client.responses.create(
            model=os.getenv("FIT_MODEL", "gpt-5.6-luna"),
            instructions=SYSTEM,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url}
                ]
            }],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "fit_recommendation",
                    "schema": SCHEMA,
                    "strict": True
                }
            }
        )
        return JSONResponse(json.loads(response.output_text))
    except Exception as e:
        return JSONResponse({"error": "AI request failed. Check the server configuration and API access.", "details": str(e)}, status_code=500)
