# AI Fit Consultant v17 — Exact Product Try-On

## What changed
- Added `/api/try-on-exact`.
- The customer photo is always the first image reference.
- Optional exact product photos can be supplied for top, bottom, outerwear, footwear, and accessory.
- GPT Image 2 receives the customer photo plus the uploaded product references in one edit request.
- Added a new **Exact Product Try-On** section in the frontend.
- Customers can change only one component (top, bottom, outerwear, footwear, or accessory) and regenerate without rebuilding the whole look.
- The existing v16 builder still works and seeds the v17 selector when the user chooses “Try this exact look”.

## Important production note
The product catalog currently contains names and demo icons, not licensed retail photography. For an exact product experience, attach the real product photo to each selected item, or later connect the catalog to your own licensed/owned product-image storage.

## Render
Build command:
`pip install -r requirements.txt`

Start command:
`uvicorn app:app --host 0.0.0.0 --port $PORT`

Environment variable:
`OPENAI_API_KEY` = your OpenAI API key (Render only; never commit it to GitHub).

Optional image settings:
- `FIT_IMAGE_MODEL` (default `gpt-image-2`)
- `FIT_IMAGE_QUALITY` (default `medium`)
- `FIT_IMAGE_SIZE` (default `1024x1536`)
- `FIT_IMAGE_INPUT_FIDELITY` (default `high`)
