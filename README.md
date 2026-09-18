# AI Fit Consultant v5

A validation MVP that recommends a seller size using:
- Full-body photo as visual context (not exact body measurement)
- Height and optional weight
- Optional direct shopper measurements (chest, waist, shoulder, inseam)
- Seller size chart entered as text and/or uploaded as a screenshot/photo
- Seller chart measurement type (body, garment, or unknown)
- Clothing category and preferred fit

## Deploy on Render

Build command:
```bash
pip install -r requirements.txt
```

Start command:
```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Environment variable:
```text
OPENAI_API_KEY=your_api_key
```

Optional:
```text
FIT_MODEL=gpt-5.6-luna
```

## Accuracy approach

The app deliberately treats direct measurements as stronger evidence than height/weight and treats the photo as visual context only. It also asks whether seller chart numbers are body or garment measurements. If this is unknown or important measurements are missing, the model should lower confidence and explain the uncertainty.

## Important

This is an advisory sizing tool, not a guarantee of fit. Before commercial use, validate it against real products, seller charts, customer measurements, purchases, returns, and exchanges.
