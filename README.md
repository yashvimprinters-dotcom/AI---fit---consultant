# AI Fit Consultant v3 — Validation MVP

## What changed
- Mobile-first consumer UI.
- Retailer-ready API design.
- Uses `gpt-5.6-luna` by default for cost-sensitive, high-volume use.
- Structured JSON response.
- No photo is saved by this application.
- Clear accuracy limitations and privacy notice.
- Demo mode for testing the interface without an API key.
- Built for one-category-at-a-time validation.

## Run locally
```bash
pip install -r requirements.txt
export OPENAI_API_KEY="your_key"
uvicorn app:app --host 0.0.0.0 --port 8000
```

Windows PowerShell:
```powershell
$env:OPENAI_API_KEY="your_key"
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open http://127.0.0.1:8000

## Demo mode
Open the site and switch on Demo Mode. This tests the interface without sending a photo to an AI model.

## Retailer plan
The `/api/recommend` endpoint is intentionally separated from the UI so it can later power:
- an embedded "Find My Fit" button,
- a Shopify-style app,
- marketplace integrations,
- retailer dashboards.

## Critical validation
Do not market this as guaranteed sizing. Collect:
1. recommendation,
2. purchased size,
3. kept/exchanged/returned,
4. reason for exchange/return,
5. optional customer feedback.

Then calculate recommendation accuracy and size-related return rate before charging retailers.
