# FITORA V34 — Monetization + Refer & Earn

## Added
- Refer & Earn card in the customer account menu.
- Personal FITORA referral code and shareable invite link.
- Copy/share buttons using the Web Share API when supported.
- Incoming `?ref=` codes are retained locally as a pending referral marker.
- Referral rewards are intentionally not faked client-side. Real cross-device rewards require server-side accounts/database and fraud controls.
- AdSense-ready loader: if `ADSENSE_CLIENT_ID` is configured in Render, the browser loads the Google AdSense script and reveals the sponsored slot.
- No OpenAI or other secret is exposed to the browser.

## Important ad policy design
- Do not reward users for clicking ads.
- If rewarded ads are later added, use only non-transferable in-app rewards and require explicit opt-in.
- Do not promise cash, gift cards, or cash-equivalent rewards for ad views/clicks.

## Render configuration for web ads
Set a non-secret environment variable:
`ADSENSE_CLIENT_ID=ca-pub-XXXXXXXXXXXXXXX`

The site must be approved/eligible for the chosen Google ad product before ads will actually serve. Do not add a fake publisher ID.

## Referral rewards
For production rewards, add authenticated accounts + database tables for users, referrals, reward ledger, and fraud/abuse checks. The current UI only creates/shares the referral identity; it does not pretend that a referral has been completed or grant fake credits.
