# AI Fit Consultant v11

A FastAPI web app for clothing size recommendations, colour selection, outfit styling, and AI visual try-on.

## v11 features
- Clothes Fitting section with seller size chart text/image, body measurements, fit preference, and conservative size recommendation.
- Colour & Visual Try-On section with a large colour library, custom colour picker/name, outfit library, custom outfit, occasion, footwear, bottom colour and accessories.
- **Build My Look**: asks the AI for 3 complete looks based on the customer's category, fit, occasion, undertone and current colour/outfit choice. Each look can be applied directly to the try-on controls.
- Visual try-on endpoint edits the customer's uploaded photo using the configured image model.
- Save/share generated preview.
- No intentional server-side storage of uploaded photos; temporary try-on files are removed after the request.

## Render
Build command:
`pip install -r requirements.txt`

Start command:
`uvicorn app:app --host 0.0.0.0 --port $PORT`

Required environment variable:
`OPENAI_API_KEY`

Optional:
`FIT_MODEL` (default `gpt-5.6-luna`)
`FIT_IMAGE_MODEL` (default `gpt-image-2`)
`FIT_IMAGE_QUALITY` (default `medium`)

## Important
Visual try-on is a styling preview, not an exact garment-fit guarantee. The fitting recommendation is also an estimate and should be checked against the seller's return/exchange policy when uncertain.


## v12 additions
- AI-suggested footwear and accessories are shown with each complete look.
- Quick-select footwear choices and accessory choices are available before visual try-on.
- Customers can override AI suggestions with their own footwear/accessory choices.
