# AI Fit Consultant v8

An AI clothing fit, color, outfit, and visual try-on MVP.

## Features
- Seller size recommendation from the supplied size chart.
- Seller chart text or screenshot extraction.
- Direct body measurements, with height/weight as secondary context.
- Color guidance using user-selected undertone and visible color context.
- A broad preset color library plus a custom color field.
- A broad outfit library plus a custom outfit field.
- AI visual try-on preview using the uploaded shopper photo.
- Try-on prompt preserves identity, pose, body proportions, and background as much as the image model can.
- Visual try-on is explicitly a styling preview, not an exact fit/measurement guarantee.

## Deploy on Render

Build command:
```bash
pip install -r requirements.txt
```

Start command:
```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Required environment variable:
```text
OPENAI_API_KEY=your_api_key
```

Optional model settings:
```text
FIT_MODEL=gpt-5.6-luna
FIT_IMAGE_MODEL=gpt-image-2
FIT_IMAGE_QUALITY=medium
```

The text recommendation uses the Responses API. The visual try-on uses the OpenAI Image Edit API with GPT-Image-2.

## Important
The try-on image is a visual approximation. It can make mistakes in garment construction, proportions, colors, or fit. It should not be presented as a measurement-accurate virtual fitting-room result.

Uploaded photos are processed for the request and the MVP does not intentionally persist them. Before commercial use, add appropriate privacy controls, consent, retention rules, and testing against real products and customer feedback.
