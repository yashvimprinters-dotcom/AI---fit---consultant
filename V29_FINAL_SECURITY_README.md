# FITORA Final Hardening (v29)

This release combines the v28 customer UI and v27 token-reduction work with production-oriented application hardening.

## Security controls included

- OpenAPI/Swagger/ReDoc endpoints disabled in production.
- HTTPS security headers: HSTS (when served over HTTPS), `X-Content-Type-Options`, `X-Frame-Options`, strict Referrer-Policy and Permissions-Policy.
- Content-Security-Policy for the current single-page app.
- Request-size ceiling before FastAPI parses large uploads.
- Per-IP/per-endpoint throttling for AI and image endpoints to reduce abuse and unexpected provider spend.
- Maximum upload size of 8 MB per image.
- MIME allow-list for JPG/PNG/WebP plus file-signature validation.
- No application-level retries for provider rate limits.
- Image-generation concurrency cap to prevent bursts.
- Provider/API errors no longer expose exception text or stack traces to customers.
- User text fields have explicit length limits before entering AI prompts.
- Generated saved-image URLs are validated before being inserted into the DOM.
- `OPENAI_API_KEY` remains server-side and is not included in the frontend.
- `.env` and Python bytecode are ignored by Git.

## Important deployment security

1. Keep the GitHub repository private if the source code is proprietary.
2. Store `OPENAI_API_KEY` only in Render Environment Variables.
3. Rotate the API key immediately if it was ever pasted into GitHub, screenshots, chat, or client-side JavaScript.
4. Enable billing/usage alerts and a provider spending limit appropriate for the business.
5. Use HTTPS only (Render's public service should already be HTTPS).
6. If FITORA adds real accounts, payments, or cloud-saved customer data, add server-side authentication, authorization, CSRF/session controls, database access controls, audit logging and a managed distributed rate limiter before launching those features.

## Limits

No web application can honestly be described as impossible to hack. This release reduces common attack and abuse paths; it is not a substitute for a professional penetration test, dependency scanning, secrets scanning, managed WAF/rate limiting, backups, and incident-response procedures for a commercial launch.

The controls are aligned with the current OWASP Top 10:2025 categories and OWASP API Security Top 10 guidance, particularly broken access control, security misconfiguration, authentication failures, logging, unsafe API consumption and unrestricted resource consumption.
