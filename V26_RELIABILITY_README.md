# FITORA v26 — Reliability & Customer Experience

This version is based on v25 and focuses on production reliability without making the customer journey more complicated.

## Main fixes
- OpenAI SDK retries are disabled at the application client layer to avoid repeated failed requests adding rate-limit pressure.
- AI JSON requests use bounded output budgets.
- `/api/recommend` has an offline sizing/style fallback when live AI is rate-limited and the seller chart is provided as text.
- `/api/build-look` has a built-in three-look fallback when live AI is rate-limited.
- AI rate-limit responses are HTTP 429 with customer-safe error codes instead of raw provider diagnostics.
- Frontend no longer shows raw OpenAI errors in browser alerts.
- Non-JSON server responses are handled gracefully.
- Exact-product try-on disables all generation/change buttons during an active request to prevent duplicate concurrent jobs.
- Saved look storage is capped and very large generated image data is not stored in localStorage.
- Health endpoint reports app version, configured AI model, and whether an API key is configured (never the key itself).

## Important
The current OpenAI error is an organization/model token-rate limit. Application code cannot increase that provider limit. The app is therefore designed to remain useful for sizing and look-building while live AI is unavailable. Visual try-on still requires the image service to be available.

## Render
Keep `OPENAI_API_KEY` only in Render Environment Variables. Optional:
- `FIT_MODEL` — text recommendation model; default `gpt-5.6-luna`
- `FIT_IMAGE_MODEL` — image model; default `gpt-image-2`
- `FIT_IMAGE_QUALITY` — image quality; default `medium`
- `FIT_IMAGE_SIZE` — default `1024x1536`
- `FIT_IMAGE_INPUT_FIDELITY` — default `high`
