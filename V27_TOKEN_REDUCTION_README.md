# FITORA v27 — Token Reduction

This version keeps the v26 reliability features and reduces API token pressure.

## What changed
- Shortened the recommendation system prompt and user prompt.
- Recommendation output cap reduced from 1400 to 800 tokens.
- Build-look output cap reduced from 900 to 500 tokens.
- Added a small in-memory cache for duplicate recommendation/look requests.
- Photo input is **not sent to the recommendation model by default** because image input is a major token cost. Size recommendations still use explicit measurements and the seller chart.
- Seller chart images are still sent when the customer uses an image chart.
- Visual try-on remains separate, so it only consumes image-model resources when the customer explicitly requests a try-on.

## Render settings
Keep `OPENAI_API_KEY` private.

Recommended:
- `FIT_MODEL=gpt-5.6-luna` (or another model after checking your OpenAI Limits page).
- `FIT_INCLUDE_PHOTO_IN_RECOMMEND=false` (default).

Set `FIT_INCLUDE_PHOTO_IN_RECOMMEND=true` only if you specifically want the recommendation call to inspect the shopper photo.

## Important
This reduces FITORA's token usage; it cannot override an OpenAI-side TPM limit. If the organization is still blocked by the provider's current rate window, the app should use its built-in local fallback until that window clears or the API limit is increased.
